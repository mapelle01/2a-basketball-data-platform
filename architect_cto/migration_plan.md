Plan de migración desde SQLite (prototipo) a PostgreSQL gestionado

Contexto:
- Prototipo actual almacena datos en SQLite.
- Objetivo: migrar a PostgreSQL (gest.) garantizando continuidad, validación y capacidad de re-procesado.

Resumen de pasos (alto nivel):
1. Preparación del entorno
   - Provisionar instancia PostgreSQL gestionada (RDS/Cloud SQL/Azure DB) con backups automáticos.
   - Crear VPC/subnet y reglas de acceso (bind restringido a IPs necesarias/servidores app).
   - Configurar secrets manager para credenciales.

2. Crear esquema en PostgreSQL
   - Aplicar el DDL en `schema_postgres_initial.sql` (archivo en repo: architect_cto/schema_postgres_initial.sql).
   - Revisar y ajustar tipos (ej: TEXT vs JSONB) según los datos reales.

3. Exportar datos desde SQLite
   - Dump estructurado: convertir tablas SQLite a CSV/JSON.
   - Herramientas: sqlite3 + scripts Python para producir JSON con mapeos para fields como dates/timestamps.
   - Validar encoding (UTF-8) y normalizar campos (trim, normalizar comillas, eliminar caracteres no imprimibles).

4. Transformación / Enriquecimiento
   - Ejecutar ETL ligero para mapear identifiers: crear una tabla de mapeo `external_id -> UUID`.
   - Rellenar campos required en Postgres (p.ej. season_id, competition_id). Si no existen, crear registros "placeholder" con metadata indicando origen.

5. Carga inicial (small batch)
   - Insertar en Postgres usando COPY o batches transaccionales.
   - Validar conteos y checksums por tabla.

6. Validación
   - Ejecutar queries de verificación: conteos por tabla, checksums por registros, integridad referencial.
   - Comparar muestras (por ejemplo 10 partidos seleccionados aleatoriamente) y verificar player/team stats.

7. Switch / Cut-over
   - Poner el sistema en modo "read-only" o pausar ingesta en prototipo (si aplica).
   - Redirigir la aplicación (services) para que lean/escriban en Postgres.
   - Monitorizar errores y latencias.

8. Reprocesado / Backfill
   - Dado que se guardan JSON raw, ejecutar pipelines (Normalizer -> Persister) reprocesando raw desde S3 o desde archivos guardados, para asegurar que las reglas de normalización se aplican de forma consistente.

9. Rollback plan
   - Conservar backup consistente de SQLite y snapshot de Postgres pre-cutover.
   - En caso de error severo, detener servicios y restaurar desde snapshot previo.

10. Post-migración
   - Habilitar monitorización y alertas (errors ingestion, queue lag, DB alarms).
   - Planificar particionamiento y mantenimiento (vacuum, reindex) según crecimiento.

Notas operativas y recomendaciones:
- Realizar la migración en un entorno staging antes de prod.
- No hacer transformaciones irreversibles durante la carga inicial: preferible guardar data raw en JSONB y normalizar por etapas.
- Añadir tests de contrato que validen estructuras del JSON antes de cada despliegue.

Tiempos estimados:
- Preparación infra: 1–3 días
- Desarrollo scripts ETL y tests: 3–7 días
- Carga inicial y verificación: 1–3 días
- Cut-over y monitorización: 1 día

Criterios para marcar migración como exitosa:
- Todas las queries críticas devuelven los mismos resultados que SQLite (muestras verificadas).
- Ingesta de nuevos partidos funciona sin errores.
- Backups automáticos activos y pruebas de restore realizadas.

