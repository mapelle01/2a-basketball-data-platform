# FASE 21.B3 — Persistencia de estadísticas FEB

**Estado: COMPLETE / PRODUCTION VERIFIED**  
**Fecha de cierre: 2026-08-14**

## 1. Objetivo

B3 completa el flujo de estadísticas de BoxScore FEB: parseo del BoxScore real, emisión del comando `upsert_match_stats`, persistencia de estadísticas de jugadores y equipos, proyección consultable, idempotencia, autorización y soporte equivalente para SQLite y PostgreSQL.

## 2. Resultado final

| Área | Estado | Evidencia |
|---|---|---|
| Parser FEB BoxScore | PASS | Fixture real + tests de conector |
| Command `upsert_match_stats` | PASS | Contrato JSON + wiring + handler |
| Player stats | PASS | 21 jugadores persistidos en producción |
| Team stats | PASS | 2 equipos persistidos en producción |
| Player REID `2813013` | PASS | 12 pts / 6 reb / 1 ast |
| Team totals | PASS | Proyección `match_team_stats` |
| Idempotencia | PASS | `command_id` + claves UNIQUE/UPSERT |
| SQLite | PASS | Repositorio + migración 003 + tests |
| PostgreSQL | PASS | Repositorio + migración 002 + tests |
| Round-trip | PASS | Serialización/deserialización de stats |
| MatchNotFound | PASS | Handler + tests |
| AuthZ | PASS | `upsert_match_stats` requiere `editor`; anónimo → 401 |
| Contract compliance | PASS | `upsert_match_stats.v1.json` |
| Secrets | PASS | Credenciales únicamente por entorno |
| API | PASS | Ingesta real contra production |
| Production DB | PASS | 21 player rows + 2 team rows verificados |
| Full test suite | PASS | **527 passed, 0 failed** |

## 3. Cambios implementados

### Conector

- Parseo completo del formato BoxScore FEB real.
- 21 jugadores detectados (10 + 11).
- Estadísticas individuales separadas del comando de creación/actualización del match.
- Team totals derivados de `TOTAL`.
- `command_id` de estadísticas determinista y separado del namespace del comando de match.
- `raw` de `create_or_update_match` permanece contract-compliant.
- Campos opcionales ausentes reciben `0` mediante defaults seguros.

### Aplicación y dominio

- Nuevo `UpsertMatchStatsHandler`.
- `Match.record_stats` mantiene las estadísticas en el agregado.
- Validación del contrato `commands/upsert_match_stats.v1.json`.
- `upsert_match_stats` registrado en `COMMANDS`, `COMMAND_ROLES` y wiring.

### Persistencia

- Nueva abstracción `MatchStatsRepository`.
- Implementaciones SQLite y PostgreSQL.
- Proyecciones:
  - `match_player_stats`
  - `match_team_stats`
- Restricciones UNIQUE para evitar duplicados.
- Consultas por partido y por temporada.
- Migraciones non-destructive:
  - SQLite: `003_match_stats.sql`
  - PostgreSQL: `002_match_stats.sql`

## 4. Idempotencia

La idempotencia se valida en dos niveles:

1. El `command_id` se registra en la infraestructura de idempotencia.
2. Las proyecciones utilizan claves únicas y operaciones UPSERT.

La reingesta del mismo comando no genera nuevos eventos ni duplica estadísticas.

## 5. Validación offline

El fixture `boxscore_2486864.json` permitió verificar el parseo antes de producción. El dry-run produjo:

- Match command: `c86e1174-6e78-5487-99ca-baabda55ddda`
- Stats command: `01ee4e73-9b0f-5022-ad02-88d4083131a5`
- 2 equipos
- 21 jugadores

## 6. Validación de producción

La ingesta real se ejecutó contra:

`https://feb-score-api-production.up.railway.app`

Resultado final:

```text
OK external_id=2486864 command_id=c86e1174-6e78-5487-99ca-baabda55ddda HTTP 200
stats OK external_id=2486864 command_id=01ee4e73-9b0f-5022-ad02-88d4083131a5 HTTP 200
```

La API confirmó el match `2486864` y PostgreSQL fue inspeccionado mediante el túnel Railway. La proyección devolvió:

- **21 filas** en `match_player_stats`.
- **2 filas** en `match_team_stats`.
- REID `2813013`: **12 puntos, 6 rebotes, 1 asistencia**.

El endpoint `/ready` también respondió:

```json
{"status":"ready","checks":{"schema_version":"2","database":"ok","migrations":"up_to_date"}}
```

## 7. Incidencias encontradas y resueltas

### Token FEB

El primer intento de producción falló con HTTP 401 porque el token FEB había cambiado. Se obtuvo el token actualizado desde la consola de red del frontend FEB y la autenticación del origen volvió a funcionar.

### API key de producción

El API rechazó inicialmente el comando con `UNAUTHENTICATED` porque `FEB_API_KEY` no era la credencial de producción correcta. Tras configurar la key `prod:admin`, la ingesta respondió HTTP 200.

### Import de tests

La ejecución de pytest llegó a fallar durante collection por `ModuleNotFoundError: No module named 'tests'`. Se resolvió haciendo `tests` un paquete mediante `tests/__init__.py`.

Después de la corrección:

```text
527 passed in 8.08s
```

## 8. Seguridad

No se incorporaron credenciales al repositorio. Los tokens y API keys se suministran mediante variables de entorno. Las credenciales utilizadas durante la validación no forman parte de este documento.

## 9. Git

B3 quedó integrada en `main` mediante:

`1fe051f feat(21.B3): persist FEB match player and team stats`

La corrección posterior de importabilidad de tests quedó en:

`debf61e test: make tests package importable`

El árbol de trabajo fue verificado limpio al finalizar.

## 10. Criterio de cierre

B3 se considera **COMPLETE** porque todos los criterios funcionales y técnicos definidos para la fase fueron verificados, incluyendo la prueba real contra producción.

No quedan blockers funcionales conocidos para B3.

**FASE 21.B3: COMPLETE / PRODUCTION VERIFIED**
