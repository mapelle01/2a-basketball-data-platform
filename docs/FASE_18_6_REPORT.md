# FASE 18.6 — BACKUP/PITR, RESTORE DRILL Y ROLLBACK CON EVIDENCIA REAL

Fecha: 2026-08-13
Alcance: cerrar los gaps operativos de staging en Railway (backup/DR, restore drill y rollback) con evidencia real, sin simulaciones, y sin destruir staging.

## Resumen

- **Backup/PITR**: operativo. PITR habilitado (bucket `Postgres-PITR` cableado), pgBackRest con primer **full backup completado** + WAL continuo archiving al bucket en tiempo real (6.8 MB / 1.363 objetos, creciendo durante la sesión). RPO efectivo ~60s (WAL).
- **Restore drill**: ejecutado y **validado** con un dato de prueba marcado (`restore-drill-test-1786650583`) presente en la instancia restaurada. RTO observado **39s**.
- **Rollback**: ejecutado y **verificado** (redeploy del deployment anterior + restauración del original). `/health`, `/ready`, datos intactos y smoke PASS en ambos sentidos.
- **Limitación real documentada**: backup on-demand y schedule diario via CLI fallan con `OAUTH_INSUFFICIENT_GRANT` (permiso de la sesión OAuth); el PITR continuo sí opera.
- **Cambio de código: ninguno.** Solo infraestructura/configuración en Railway + documentación.

## Tabla de criterios

| Criterio | Status | Evidencia (real) |
|---|---|---|
| PITR habilitado | ✅ PASS | `railway postgres pitr status` → Status: **enabled**, Bucket wired: **yes**, Service: Postgres, Environment: production |
| Bucket de backup | ✅ PASS | Bucket `Postgres-PITR` (id `16bc5fdc-...`, región **ams**, S3 `postgres-pitr-kjuqowfazu`) |
| Full backup base | ✅ PASS | Logs Postgres: `backup command end: completed successfully (50213ms)`; `stanza-create` OK |
| Retención | ✅ PASS | `expire command end: completed successfully` con `--repo1-retention-full=4 --repo1-retention-diff=14` (~4 semanas de ventana) |
| WAL continuo (RPO ~60s) | ✅ PASS | Logs: `archive-push command end: completed successfully`; bucket creció 1.346 → **1.363 objetos** (6.8 MB) durante la sesión |
| Backup on-demand | ⚠️ BLOCKED | `railway postgres pitr backup create` → `OAUTH_INSUFFICIENT_GRANT` (también tras re-login) |
| Schedule diario | ⚠️ BLOCKED | `railway postgres pitr schedule set --daily` → `OAUTH_INSUFFICIENT_GRANT` |
| Dato de prueba para restore | ✅ PASS | `POST /v1/commands/create_or_update_match` external_id `restore-drill-test-1786650583` → HTTP 200, `status=accepted`, evento `match_upserted`; `GET /v1/matches/...` → 200 |
| Restore PITR | ✅ PASS | `railway postgres pitr restore --service Postgres --at 2026-08-13T19:51:20Z --new-service-name feb-restore-drill` → "Started a point-in-time restore…"; servicio temporal **Online** (deployment `26752347`) |
| RTO restore (observado) | ✅ PASS | `restore_start=19:51:20Z` → `restore_completed=19:51:59Z` = **39s** (objetivo provisional 4h) |
| Schema en instancia restaurada | ✅ PASS | `schema_version=1`; **12 tablas** public |
| Datos en instancia restaurada | ✅ PASS | `matches=2`; `test_match=restore-drill-test-1786650583` presente; `domain_events=2`; `drill_eventos=1`; match con `competition_id=restore-comp` y `status=SCHEDULED` |
| Cleanup del drill | ✅ PASS | `railway service delete --service feb-restore-drill --yes` → solo quedan `feb-score` y `Postgres` |
| Rollback (deploy anterior) | ✅ PASS | `deploymentRedeploy(id:"7dbeda3b-...")` → nuevo deployment `755a4c77` **SUCCESS** |
| Post-rollback health/ready | ✅ PASS | `/health` 200 `{"status":"ok"}`; `/ready` 200 `{"status":"ready","checks":{"schema_version":"1","database":"ok","migrations":"up_to_date"}}` |
| Post-rollback datos intactos | ✅ PASS | `GET` match `restore-drill-test-1786650583` → 200; `GET` match `smoke-1786649868` → 200 |
| Post-rollback smoke | ✅ PASS | `scripts/staging_smoke.sh` → `STAGING SMOKE OK` (POST accepted + match_upserted, GET 200) |
| Restauración del estado original | ✅ PASS | `deploymentRedeploy(id:"0f0c8310-...")` → `f997d479` **SUCCESS** (~150s) |
| Post-restauración final | ✅ PASS | `/health` 200, `/ready` 200, smoke PASS (external_id `smoke-1786651566`) |
| Tests locales | ✅ PASS | `scripts/ci.sh` → exit 0, **477 passed** in 6.35s |
| PostgreSQL 18 vs 16 | ℹ️ DOC | Imagen `postgres-ssl:18` (PostgreSQL 18, default actual del plugin Railway); **no se cambia**; CI usa 16 localmente, la API es agnóstica |

## Detalle de comandos y observaciones

- **SSH**: para conectar al Postgres privado por túnel (`railway connect`) se generó y registró la clave `~/.ssh/railway_opencode` (`railway ssh keys add`). Sin esto, `railway connect` no abre el túnel.
- **Sonda de cobertura "best effort"**: `Live coverage` del CLI muestra `unavailable (SSH command failed exit status 10)` — limitación de la sonda (usa la clave ssh por defecto del agente, no la recién registrada). La operatividad real del backup se verifica por el bucket (objetos creciendo) y por los logs pgBackRest, no por esa sonda.
- **Credenciales**: `FEB_SCORE_API_KEYS` (key de smoke) y `FEB_SCORE_DATABASE_URL` nunca impresos; la key vive en `/tmp/feb_smoke_key` (0600) y se recomienda **rotarla** al cierre de la fase.

## STAGING GATE

**PASS — STAGING READY (con 2 limitaciones documentadas, sin evidencia inventada)**

- ✅ BACKUP OPERATIVO: PITR + WAL continuo a bucket (RPO ~60s), full backup + retención verificados por logs pgBackRest.
- ✅ RESTORE DRILL REAL: restaurado a timestamp y validado (schema + datos marcados + eventos).
- ✅ ROLLBACK REAL: deploy anterior redeployeado y verificado; estado original restaurado.
- ⚠️ BACKUP ONDEMAND / SCHEDULE: BLOCKED por `OAUTH_INSUFFICIENT_GRANT` (a documentar como pendiente: dashboard o credencial con más grants).
- ⚠️ CAPA OFFSITE (`pg_dump -Fc` a bucket externo): pendiente (recomendado para portabilidad fuera de Railway).

No se declara PRODUCTION DEPLOYED. El siguiente trabajo sería producción (otra fase), no staging.