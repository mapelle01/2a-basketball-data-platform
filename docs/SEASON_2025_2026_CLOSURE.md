# SEASON 2025-2026 CLOSURE (2aFEB_SCORE)

**Fecha:** 2026-08-16
**Fase:** FASE 22.6 COMPLETA
**Estado:** SEASON INGESTION CLOSED

Este documento certifica el cierre oficial del ciclo de ingesta de la temporada 2025-2026 para el pipeline FEB en `2aFEB_SCORE`. Todos los datos de la temporada regular (grupos ESTE y OESTE) han sido capturados, procesados y validados en producción.

---

## 1. Estado Final

Los datos persisistidos y validados en PostgreSQL de producción son los siguientes:

* **Temporada:** `2025-2026`
* **Competición:** `segunda-feb`
* **Grupos:** ESTE + OESTE
* **Jornadas:** 26 por grupo
* **Partidos:** 364
* **Player stats:** 8.230
* **Team stats:** 728
* **Duplicados:** 0
* **Jornadas sin datos:** 0
* **Partidos sin estadísticas:** 0
* **`round_number`:** 1..26 correcto (7 partidos por jornada y grupo)
* **`/ready` endpoint:** PASS
* **Schema version:** v2
* **Migrations:** up to date
* **Tests:** 628 passed

---

## 2. Pipeline de Ingesta

El flujo completo de ingesta utilizado para toda la temporada fue:

`FEB discovery` → `match ingestion` → `stats ingestion` → `PostgreSQL` → `validación` → `replay/idempotencia`.

### Diferencia en el mecanismo de Discovery (ESTE vs OESTE)

La fuente FEB requirió dos estrategias distintas de discovery para los grupos:

* **ESTE:** El listado de partidos y jornadas pudo obtenerse mediante un simple método **GET**.
* **OESTE:** La infraestructura de FEB ocultaba los datos detrás de una vista ASP.NET tradicional. Fue necesario construir una petición **POST** específica (WebForms `_ctl0:token`, viewstates) para simular el cambio de pestaña y recuperar el fixture del grupo OESTE.

A pesar de esta divergencia en la capa más externa de scraping, **ambos grupos terminan inyectándose en el mismo pipeline** de `create_or_update_match` y `upsert_match_stats`, lo que garantiza homogeneidad total en la base de datos de producción.

---

## 3. Integridad y Garantías Verificadas

A lo largo del backfill completo, se han demostrado las siguientes garantías arquitectónicas:

* **Idempotencia:** El replay de toda la temporada (ESTE y OESTE) resulta en 0 partidos duplicados y 0 estadísticas duplicadas. La base de datos es estable frente a inyecciones repetidas de los mismos datos.
* **Ausencia de duplicados:** Validado por los constraints y la verificación de los totales (exactamente 364 partidos y 728 team stats).
* **Persistencia de estadísticas:** Asegurada al 100%. Todo partido tiene sus `match_team_stats` y `match_player_stats` correspondientes extraídos del BoxScore.
* **Propagación del `round_number` real:** Los metadatos de jornada provistos por la FEB se extraen correctamente de las cabeceras/tablas HTML y se persisten de manera fiable, sin recurrir a adivinaciones.
* **Retry controlado de HTTP 429:** El pipeline demostró robustez ante el límite de tasa (rate limits) de la API FEB, aplicando backoff exponencial y recuperándose sin pérdida de datos.
* **Separación entre source connector y backend:** El parser que "habla" ASP.NET o navega el DOM no contamina el modelo de dominio. Todos los datos ingresan al sistema como comandos estructurados y tipados.
* **Seguridad (No exposición de tokens):** En ningún momento del loggin, parsing o persistencia se exponen los viewstates sensibles ni los JWT, garantizando una ejecución segura y auditable.

---

## 4. Incidentes Observados

Durante la operación real de backfill contra los servidores de la FEB, registramos:

* **HTTP 429 transitorios (Grupo ESTE):** La ejecución inicial topó con rate limits del servidor LiveStats. Se resolvió mediante la resiliencia del pipeline (mecanismo automático de retries).
* **HTTP 500 transitorio de FEB (Grupo OESTE):** Durante un replay del grupo OESTE, el endpoint oficial `intrafeb.feb.es/.../BoxScore` devolvió un error de servidor interno HTTP 500 generalizado durante aproximadamente 60 segundos. Al ser un problema del lado emisor, no afectó al estado de producción. Una vez restaurado el servicio de la FEB, el replay finalizó exitosamente.
* **Endpoint incorrecto `FEB_BOX_SCORE_BASE_URL`:** Se detectó en un momento que el entorno inyectaba una variable incorrecta, lo que causó fallos de conexión. La herramienta supo recurrir al _default_ correcto del código (o usar la URL proporcionada) sin generar inyecciones parciales ni corrupción.

**Conclusión de incidentes:** Ninguno causó corrupción, falsos positivos ni pérdida de datos. Los replays finales siempre fueron de estado **PASS**.

---

## 5. Limitaciones Conocidas

* **Dependencia crítica del HTML/ASP.NET de FEB:** Aunque la ingestión es robusta, seguimos fuertemente acoplados a la estructura del frontend (ASP.NET WebForms) de competiciones FEB. Un cambio en sus clases CSS, IDs de tablas, o en el sistema de tokens del ViewState (particularmente para el grupo OESTE) rompería el Discovery Connector inmediatamente, requiriendo intervención técnica.
* **Datos históricos en BoxScore:** Si la FEB edita un acta días después del partido, actualmente el sistema no se entera a menos que forcemos un replay explícito de dicho `external_id`.

---

## 6. Conclusión de Cierre

El ciclo de ingesta de la **temporada 2025-2026 queda oficialmente cerrado**.

Los **364 partidos** están completos, saneados, estandarizados y expuestos en PostgreSQL en el entorno de Producción. La capa de datos brutos del proyecto es considerada estable y lista para ser consumida como base fiable en la construcción de la siguiente capa analítica del producto.
