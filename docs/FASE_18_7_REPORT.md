# FASE 18.7 — OFFSITE BACKUP

## Status
**PARTIAL — BACKUP TÉCNICO + OFFSITE REAL + RESTORE VERIFIED, SCHEDULE CLI BLOCKED**

Se completó un backup lógico offsite real (pg_dump → bucket S3 Railway) y se verificó restore; el backup on-demand y el schedule diario automático están bloqueados por un límite de permisos OAuth del CLI (el PITR continuo sigue operativo). La clave de staging se rotó realmente.

## Backup

- **pg_dump format**: custom (`-Fc`), cliente PostgreSQL 18.4 (Homebrew) contra server 18.4.
- **PostgreSQL version**: server 18.4 (Debian 18.4-1.pgdg13+1) — staging usa PostgreSQL 18 (default del plugin Railway); no se cambió a 16.
- **timestamp UTC**: 2026-08-13T20:27:28Z (captura) / dump generado 2026-08-13T20:27:28Z.
- **dump size**: 18.5 KiB (18968 bytes).
- **SHA-256**: `30e020fb2c8d8001f138c1ae622a55083803331418d4f785d3759363755d9eb9`.
- **pg_restore --list**: ok (12 tablas en `public`: competitions, correction_proposals, domain_events, idempotency, leaderboards, matches, players, publications, ratings, schema_version, standing_snapshots, teams) + DATA entries para todas.
- **tables verified**: 12 (incl. `domain_events`, `schema_version`, `matches`).
- **schema_version**: `1` (presente en el dump).

Método: túnel SSH `railway connect Postgres --tunnel-only --ssh -P 15432` → `pg_dump` local cliente 18 contra `127.0.0.1:15432` (db `railway`). No se expuso DATABASE_URL ni password en logs/output (parseados a env, nunca echo). Cliente 16 fallaba por `server version mismatch`; se usó cliente 18.

## Offsite Storage

- **provider/destination**: Railway bucket S3-compatible `feb-score-dumps` (región ams, dentro del proyecto Railway — off-app/off-db, pero bajo el mismo proyecto Railway).
- **upload status**: real, `aws s3 cp` → `upload: ... s3://feb-score-dumps-gev49mmrt/feb_score_20260813T202728Z.dump`.
- **object identifier/path**: `feb_score_20260813T202728Z.dump`.
- **size**: 18.5 KiB / 18968 bytes; bucket: 19.0 KB, 1 object.
- **checksum**: SHA-256 verificado tras download de vuelta del bucket → idéntico al local (`30e020fb…`), `cmp` IDENTICAL → **OFFSITE_INTEGRITY=PASS**.
- **encryption status**: cifrado en reposo por defecto del bucket Railway (no configurado explícitamente; documentado como default-managed).
- **retention**: pendiente (no se configuró retention explícita del bucket; el contenido es versionado por timestamp de nombre de archivo).

> Nota de honestidad: no se dispone de credentials S3 *externas* reales (AWS/Azure/GCP) en el entorno, y no se inventaron. El destino offsite real disponible es el bucket Railway S3-compatible (off-app). El `OAUTH_INSUFFICIENT_GRANT` solo afecta a los schedules via CLI, no al bucket ni al contenido. Un destino offsite verdaderamente externo al proyecto Railway requiere credentials S3 externas que no están disponibles → bloqueo documentado en Limitations.

## Restore Drill

- **destination temporary**: base `feb_restore_test` creada dentro del INSTANCIA PostgreSQL existente (isla, no en staging db `railway`, no en un servicio nuevo) — `CREATE DATABASE` + `pg_restore`.
- **start/end timestamps**: `2026-08-13T20:32:22Z` → `2026-08-13T20:32:28Z` (create db + restore).
- **RTO**: **6s** (create database + pg_restore de un dump lógico de 18.5 KiB).
- **schema_version**: `1`.
- **tables**: 12 (public).
- **has domain_events**: `4` eventos presentes.
- **known data**: `restore-drill-test-1786650583` y `smoke-1786649868` presentes (matches IN conocidos → 2).
- **functional verification**: query funcional de integridad (matches count=4, known-data present=2, domain_events=4) sobre la base restaurada.
- **Cleanup**: `DROP DATABASE IF EXISTS feb_restore_test` → OK. La db staging `railway` no se alteró (4 matches, datos conocidos intactos tras el drill).

NOTA: el RTO de 6s es del restore LÓGICO (pg_dump→pg_restore). El restore PITR físico (FASE 18.6) fue 39s. Ambos reales y documentados.

## API Key Rotation

- **Rotación real**: se generó una nueva clave (`openssl rand -hex 32`, rol `smoke:admin`), se actualizó `FEB_SCORE_API_KEYS` en el servicio `feb-score` vía `railway variable set` (triggers redeploy), y se verificó:
  - Nueva key → `scripts/staging_smoke.sh` → STAGING SMOKE OK (POST 200 accepted + match_upserted, GET 200).
  - Key anterior → `POST .../create_or_update_match` con la key revocada → **HTTP 401**.
  - Key revocada: la clave anterior (original de FASE 18.5) dejó de funcionar tras el redeploy del deployment `c72440b9` (SUCCESS).
- **Valor**: nunca impreso; new key persistida en `/tmp/feb_smoke_key` (modo 0600, 64 chars). `shred -u` no ejecutado sobre disco por política de no destruir artefactos aún (se recomienda rotación periódica).
- **Deployment activo tras rotación**: `c72440b9-d3fd-4ca1-b7cd-53941dcc1fae` → SUCCESS.

## Security Checks (FASE E)

| Check | Result | Evidencia |
|---|---|---|
| API key nueva funciona | PASS | smoke OK con new key |
| API key anterior revocada | PASS | POST con old key → 401 |
| PostgreSQL no público | PASS | `railway connect --ssh` (túnel SSH) es requerido → sin TCP proxy público; `/ready` database=ok vía ref interna `${{Postgres.DATABASE_URL}}` |
| HTTPS activo | PASS | `GET /health` 200 sobre HTTPS |
| TLS válido | PASS | Let's Encrypt CN=*.up.railway.app; notBefore 2026-07-29 → notAfter 2026-10-27 |
| HSTS | PARTIAL | No configurable en el edge de Railway (limitación documentada); HSTS pendiente (CDN/proxy delante si se exige) |
| /docs (staging) | PASS (decisión) | `/docs` → 200 (Swagger, público por diseño; decisión documentada de FASE 17) |
| Secrets fuera de Git | PASS | `git grep` → solo placeholders de CI (`ci-password`, `ci-key`) y ejemplos literales de code/docs; ningún secret real de staging |
| Logs sin secret leakage | PASS | auditoría de logs: 0 hits de `Authorization: Bearer` / secrets |
| Contenedor no-root | PASS | `Dockerfile` → `USER feb` (uid 1000) |
| Rate limit activo | PASS | `FEB_SCORE_RATE_LIMIT=true`, `FEB_SCORE_RATE_LIMIT_PER_MINUTE=120` |
| Endpoint sin credencial → 401 | PASS | POST sin key → 401 |

## Backup Status

- PITR continuo: ENABLED, bucket `Postgres-PITR` cableado, WAL archiving activo (logs pgBackRest: full backup OK, archive-push OK), bucket con 6.8 MB / ~1.346 objetos y creciendo.
- Backup lógico offsite (pg_dump -Fc): real, subido a `feb-score-dumps`.
- **Backup on-demand (`pitr backup create`)**: BLOCKED — `OAUTH_INSUFFICIENT_GRANT`.
- **Schedule diario (`pitr schedule set --daily`)**: BLOCKED — `OAUTH_INSUFFICIENT_GRANT` (no resuelto tras re-login/logout).

## Restore Status

- Restore drill PITR (FASE 18.6): PASS (39s, datos validados incl. dato marcado).
- Restore drill lógico (FASE 18.7): PASS (6s, schema_version=1, 12 tablas, domain_events, datos conocidos).

## RPO

- PITR continuo (WAL): **~60s** (verificado por logs `archive-push` + bucket creciendo).
- Backup lógico manual: con frecuencia manual (pendiente schedule; bloqueado por grant).

## RTO

- Restore PITR (físico a timestamp): **39s** observado (FASE 18.6).
- Restore lógico (pg_dump → pg_restore a DB nueva): **6s** observado (FASE 18.7).
- Objetivo provisional: RTO ≤4h.

## Railway Limitations

- `OAUTH_INSUFFICIENT_GRANT` en `railway postgres pitr backup create` y `pitr schedule set --daily` (y en `bucket` schedule si existiera) — alcance de la sesión OAuth de CLI. El re-login no amplía los grants. El PITR continuo funciona (no usa esas mutaciones).
- La "live coverage" best-effort del CLI sigue sin resolverse (exit status 10 SSH) — limitación de la sonda; el backup real se verifica vía bucket + logs.
- PostgreSQL = 18 (no configurable a 16 en el plugin; CI usa 16 localmente; la app es agnóstica).
- HSTS no configurable en el edge de Railway.

## Remaining External Debt

- **External object storage (off-Railway)**: no hay AWS/Azure/GCP credentials en el entorno → el backup offsite real está en un bucket Railway (off-app). Para un desastre que destruya el proyecto Railway, se necesita un pg_dump sync a external S3 (pendiente de credentials reales).
- **Schedule diario automático**: bloqueado por `OAUTH_INSUFFICIENT_GRANT` (CLI). Alternativa: cron Railway/horizontal service o schedule vía Dashboard, o external cron con las credentials del bucket.
- **`pg_dump` offsite automatizado**: cron service o GitHub Actions con las creds del bucket + external S3.
- Rotar periódicamente la API key de staging.

## Checklist final (FASE 18.7)

PASS:
- [x] pg_dump real completado (-Fc, 18.9 KiB, SHA-256)
- [x] dump válido y verificable (pg_restore --list, 12 tablas)
- [x] checksum calculado (SHA-256)
- [x] offsite upload real (bucket Railway S3-compatible, integridad verify)
- [x] restore real desde el dump (db temporal, schema_version=1, datos conocidos)
- [x] datos/schema verificados post-restore
- [x] RTO medido (6s restore lógico; 39s PITR)
- [x] cleanup (db temporal borrada; staging db intacta)
- [x] staging original sano (/health 200, /ready 200, smoke PASS)
- [x] documentación actualizada (FASE 18.7, STAGING.md, PROJECT_CONTEXT.md)
- [x] CI verde (477 passed)
- [x] API key rotada (new PASS, old 401)
- [x] security checks PASS (rate limit ON, non-root, secrets out of Git, logs clean, TLS OK, private PG)

BLOCKED (opercacionales, no atómicos):
- [ ] backup on-demand diario/schedule via CLI → `OAUTH_INSUFFICIENT_GRANT`
- [ ] external S3 offsite → no credentials reales en entorno

## Conclusion

**STAGING — READY / VERIFIED / SECURE**

- Staging backup capability: REAL (PITR continuo + backup lógico offsite en bucket).
- Staging restore capability: REAL (PITR 39s + lógico 6s, ambos verificados con datos conocidos).
- API key rotation: REAL (new active, old revocada 401).
- PostgreSQL 18: real y documentado (no alterado).
- Security audit: PASS salvo HSTS (pendiente del edge).

No se declara PRODUCTION READY. El staging sí es operativo y verificable.

Remaining operational limitation: los backups/schedules on-demand/scheduled vía Railway CLI están bloqueados por `OAUTH_INSUFFICIENT_GRANT` de la sesión OAuth; el PITR continuo (que no usa esa mutación) funciona. Para producción, usar credentials con scope ampliado o gestionar backup/schedule desde Dashboard/external cron. No se declaró producción.