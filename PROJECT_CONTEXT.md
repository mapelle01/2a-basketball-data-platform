# FEB SCORE — PROJECT CONTEXT

## Plataforma de datos deportivos para competiciones FEB

**Estado del proyecto:** READY — PRODUCTION CANDIDATE · STAGING (Railway) preparado en código y documentación, BLOCKED por falta de acceso a Railway (FASE 18.1)
**Fecha de actualización:** 2026-08-13
**Objetivo:** construir una plataforma de datos deportivos especializada inicialmente en competiciones de la Federación Española de Baloncesto (FEB), inspirada funcionalmente en productos como SofaScore, FotMob o Flashscore.

---

# 1. VISIÓN DEL PROYECTO

El objetivo es construir una plataforma de datos deportivos capaz de recopilar, normalizar, almacenar y analizar información oficial de las competiciones FEB.

El producto final no debe entenderse como un proyecto de scraping ni como una herramienta para publicar contenido en Instagram.

La visión es construir un **Core Engine de datos deportivos** que pueda alimentar diferentes consumidores:

* Página web.
* Aplicación móvil.
* API.
* Instagram.
* X / Threads.
* Dashboards.
* Sistemas de analítica.
* Modelos de Machine Learning.
* Otros productos futuros.

La arquitectura debe seguir el principio:

```text
FUENTES DE DATOS
       ↓
INGESTA
       ↓
NORMALIZACIÓN
       ↓
CORE DOMAIN
       ↓
ESTADÍSTICAS
       ↓
ANALYTICS / RATINGS
       ↓
CONTENT ENGINE
       ↓
CONSUMIDORES
```

Instagram es solamente uno de esos consumidores.

---

# 2. OBJETIVO FUNCIONAL

La plataforma debe permitir construir una experiencia similar, a nivel conceptual, a SofaScore/FotMob pero centrada inicialmente en competiciones FEB.

Los principales datos de interés son:

### Partidos

* Fecha.
* Hora.
* Jornada.
* Fase.
* Competición.
* Temporada.
* Equipos.
* Resultado.
* Parciales.
* Prórrogas.
* Estado del partido.
* Pabellón.
* Árbitros.
* Incidencias cuando estén disponibles.

### Equipos

* Identidad.
* Nombre.
* Abreviatura.
* Escudo.
* Pabellón.
* Temporada.
* Competición.
* Plantillas.
* Historial.

### Jugadores

* Identidad.
* Nombre.
* Dorsal.
* Posición.
* Información disponible oficialmente.
* Registro histórico por equipo y temporada.

### Estadísticas

Por partido y, cuando sea posible, acumuladas:

* Puntos.
* Tiros de 2.
* Tiros de 3.
* Tiros libres.
* Rebotes ofensivos.
* Rebotes defensivos.
* Rebotes totales.
* Asistencias.
* Robos.
* Tapones.
* Pérdidas.
* Faltas.
* Minutos.
* Valoración.
* Otras estadísticas proporcionadas oficialmente.

### Clasificación

* Posición.
* Partidos jugados.
* Victorias.
* Derrotas.
* Puntos a favor.
* Puntos en contra.
* Diferencia.
* Racha.
* Puntuación/clasificación oficial.
* Desempates según las reglas de la competición.

---

# 3. OBJETIVO ANALÍTICO

Además de reproducir los datos oficiales, el proyecto debe generar información de valor añadido.

Entre los productos analíticos previstos:

* Player Rating.
* Team Rating.
* Power Ranking.
* Form Index.
* Leaderboards.
* Records.
* Streaks.
* Milestones.
* MVP / jugador destacado.
* Comparativas.
* Rankings históricos.

Los algoritmos deben ser:

* deterministas;
* reproducibles;
* versionados;
* independientes de la fuente original.

Por ejemplo:

```text
PlayerRating
rating_version = "1.0"
```

Esto permite recalcular resultados históricos cuando cambie un algoritmo sin perder trazabilidad.

---

# 4. FUENTE PRINCIPAL DE DATOS

La fuente principal es la web oficial de la:

**Federación Española de Baloncesto (FEB)**

La plataforma oficial proporciona información de:

* competiciones;
* temporadas;
* jornadas;
* partidos;
* resultados;
* clasificaciones;
* equipos;
* jugadores;
* estadísticas;
* boxscores;
* otros datos asociados.

La extracción debe priorizar siempre que sea posible **datos estructurados proporcionados por la propia plataforma oficial**, frente a scraping visual del HTML.

---

# 5. INVESTIGACIÓN DE LA WEB FEB

La investigación inicial mostró que la web de la FEB utiliza una arquitectura web dinámica y que parte de la información visible en el frontend procede de llamadas internas que devuelven datos estructurados.

Durante el desarrollo se identificó que determinadas páginas de partido permiten obtener un **token utilizado para realizar llamadas internas JSON** relacionadas con los datos del partido.

El prototipo actual ha demostrado que este flujo es funcional.

## IMPORTANTE

No deben considerarse como documentación oficial de la FEB:

* nombres concretos de endpoints internos;
* estructura fija de URLs;
* duración del token;
* mecanismo exacto de renovación;
* límites de rate limiting;
* nombres de determinados parámetros.

Estos elementos pueden cambiar y deben descubrirse/validarse mediante el comportamiento actual de la plataforma.

Por tanto:

> La implementación de la ingesta debe tratar la interfaz interna de FEB como una dependencia externa potencialmente cambiante.

---

# 6. ESTADO REAL DEL PROTOTIPO DE INGESTA

Existe un prototipo Python que demuestra la viabilidad técnica del proceso.

El prototipo actual ha conseguido:

1. Acceder a páginas de resultados.
2. Identificar partidos.
3. Acceder a páginas individuales de partidos.
4. Obtener el token necesario para las llamadas internas.
5. Realizar llamadas a endpoints internos JSON.
6. Guardar respuestas raw.
7. Parsear información estructurada.
8. Persistir información en SQLite.

Se validó el flujo con un partido de Segunda FEB 2025/2026.

Resultado de la prueba:

* 1 partido procesado.
* 28 filas de standings.
* 30 filas de leaderboards.
* 2 filas de team_stats.
* 24 filas de player_stats.
* respuestas raw almacenadas.

Esto demuestra que la construcción de una base histórica FEB es técnicamente viable.

---

# 7. ALCANCE ACTUAL

El proyecto se centra inicialmente en:

* Resultados.
* Clasificaciones.
* Estadísticas.
* Boxscores.
* Equipos.
* Jugadores.
* Históricos.
* Analytics derivados.

## NO es prioridad inicial

Los datos live de partidos.

La existencia de mecanismos privados relacionados con partidos en directo no forma parte del MVP actual.

La plataforma debe diseñarse de forma que el soporte live pueda añadirse posteriormente sin tener que rediseñar el Core Domain.

---

# 8. LIMITACIONES DE LA INGESTA

La extracción actual sigue siendo un prototipo.

Principales riesgos:

### Dependencia de la plataforma FEB

La FEB puede modificar:

* HTML.
* JavaScript.
* endpoints internos.
* estructura JSON.
* mecanismos de autenticación.
* tokens.
* parámetros.

### Datos incompletos

No todos los campos están necesariamente disponibles para todos los partidos, temporadas o competiciones.

### Correcciones

La FEB puede modificar posteriormente:

* resultados;
* estadísticas;
* jugadores;
* clasificación;
* información del partido.

El sistema debe soportar estas correcciones sin destruir el historial anterior.

---

# 9. ESTRATEGIA DE INGESTA

La arquitectura debe separar claramente:

```text
FEB
 ↓
Collector
 ↓
Raw Data
 ↓
Normalizer
 ↓
Validation
 ↓
Core Domain
 ↓
Persisted Domain Model
```

El Collector NO debe contener reglas de negocio.

Su responsabilidad es:

* obtener datos;
* conservar el origen;
* identificar la fuente;
* entregar el contenido al proceso de normalización.

El Normalizer transforma la estructura específica de FEB en los contratos internos de la plataforma.

Esto permite que el Core Domain no conozca detalles de la API de FEB.

---

# 10. RAW DATA

Las respuestas originales deben conservarse cuando sea necesario para:

* debugging;
* auditoría;
* reproducibilidad;
* correcciones;
* nuevas versiones del normalizador;
* reconstrucción histórica.

Conceptualmente:

```text
RAW FEB
   ↓
Normalizer v1
   ↓
Domain
```

Si posteriormente aparece:

```text
Normalizer v2
```

debe ser posible volver a procesar el raw original sin tener que consultar nuevamente FEB.

La tecnología concreta de almacenamiento raw todavía no es una decisión de dominio.

Puede comenzar como almacenamiento local durante el desarrollo y evolucionar posteriormente a almacenamiento de objetos.

---

# 11. CORE DOMAIN

El proyecto ha evolucionado desde un simple extractor hacia una plataforma basada en Domain-Driven Design (DDD).

El Core Domain es independiente de:

* FEB.
* HTTP.
* PostgreSQL.
* Kafka.
* S3.
* Redis.
* FastAPI.
* Instagram.

El dominio debe poder ejecutarse completamente en memoria.

---

# 12. BOUNDED CONTEXTS

Los principales Bounded Contexts definidos son:

### Match Management & Identity

Responsable de:

* Match.
* Team.
* Player.
* Squad.
* PlayerRegistration.
* identidad y resolución de entidades.

### Rules & Competition

Responsable de:

* Competition.
* Season.
* Round.
* reglas de competición.
* desempates.
* elegibilidad.
* finalización.

### Statistics

Responsable de:

* PlayerStats.
* TeamStats.
* estadísticas de partido.
* snapshots estadísticos.

### Standings & Leaderboards

Responsable de:

* clasificación.
* standings.
* leaderboards.
* snapshots de clasificación.

### Ratings & Analytics

Responsable de:

* PlayerRating.
* TeamRating.
* PowerRanking.
* FormIndex.
* Records.
* Milestones.

### Media & Content

Responsable de:

* Publication.
* Templates.
* Content.
* generación de contenido basado en datos.

### Administration & Audit

Responsable de:

* correcciones;
* aprobaciones;
* auditoría;
* trazabilidad;
* operaciones manuales.

---

# 13. OWNERSHIP

Cada concepto debe tener un propietario claro.

Un contexto no debe modificar directamente el modelo interno de otro contexto.

Por ejemplo:

```text
Ratings
    ✕
    ↓
MatchAggregate interno
```

En lugar de ello:

```text
Match
 ↓
Domain Event / DTO
 ↓
Ratings
```

Esto permite evolucionar cada contexto de forma independiente.

---

# 14. CONTRACTS

Se ha creado una primera versión de los contratos de dominio.

Ubicación:

```text
contracts/
├── commands/
└── events/
```

Los contratos utilizan:

**JSON Schema Draft 2020-12**

Los contratos incluyen:

* Commands.
* Domain Events.
* Versionado.
* Metadata.
* Identificadores.
* Payloads.
* Examples.

Los contratos son la interfaz entre contextos.

---

# 15. PRINCIPALES COMMANDS

Entre los Commands definidos:

* CreateOrUpdateMatch.
* FinalizeMatch.
* ProposeCorrection.
* ApproveCorrection.
* RegisterPlayerToSquad.
* GenerateStandingSnapshot.
* GenerateLeaderboard.
* ComputePlayerRating.
* CreatePublication.
* BackfillSeason.

Los comandos representan intenciones.

Ejemplo:

```text
FinalizeMatch
```

No significa que el partido ya esté finalizado.

El resultado del procesamiento puede producir:

```text
MatchFinalized
```

---

# 16. PRINCIPALES DOMAIN EVENTS

Entre los eventos definidos:

* MatchUpserted.
* MatchValidationStarted.
* MatchValidated.
* MatchFinalized.
* ValidationFailed.
* CorrectionProposed.
* CorrectionApproved.
* MatchUpdatedByCorrection.
* PlayerRegistered.
* StandingSnapshotGenerated.
* LeaderboardGenerated.
* PlayerRatingComputed.
* PlayerMilestoneReached.
* PublicationCreated.
* SeasonBackfillStarted.
* SeasonBackfillCompleted.
* CorrectionRejected.
* DomainAlert.

Los eventos representan hechos que ya han ocurrido.

---

# 17. VERSIONADO

Los contratos y algoritmos deben versionarse.

Ejemplo:

```text
Match contract v1
Rating algorithm v1
Rules v1
Normalizer v1
```

Una nueva versión no debe destruir la capacidad de interpretar datos históricos.

Especialmente importante para:

* PlayerRating.
* TeamRating.
* PowerRanking.
* standings.
* reglas de competición.
* normalizadores.

---

# 18. MATCH AGGREGATE

El Match es uno de los elementos centrales del dominio.

Debe proteger sus propias invariantes.

Entre ellas:

* equipos válidos;
* resultado válido;
* parciales coherentes;
* transición de estados válida;
* finalización válida;
* correcciones controladas.

El dominio no debe permitir que una operación externa cambie directamente el estado del Match sin pasar por sus reglas.

Conceptualmente:

```text
match.finalize()
```

debe ejecutar las validaciones necesarias antes de permitir el cambio de estado.

---

# 19. ESTADOS DEL PARTIDO

El modelo debe contemplar estados como:

```text
SCHEDULED
IN_PROGRESS
FINALIZED
POSTPONED
CANCELLED
```

Las transiciones válidas deben estar definidas por el dominio.

Un partido finalizado no debe poder volver silenciosamente a un estado anterior.

Las excepciones deben gestionarse mediante procesos explícitos de corrección.

---

# 20. CORRECCIONES

Las correcciones de datos oficiales son una parte fundamental del sistema.

Una corrección debe conservar:

* quién propuso;
* quién aprobó;
* cuándo;
* motivo;
* versión anterior;
* versión posterior;
* cambios realizados.

Nunca debe destruir silenciosamente el estado anterior.

Conceptualmente:

```text
Estado anterior
      ↓
Correction Proposed
      ↓
Correction Approved
      ↓
Nuevo estado
      ↓
Recalcular dependencias
```

Esto permitirá reconstruir cómo se obtuvo cualquier resultado histórico.

---

# 21. RATINGS Y ANALYTICS

Los ratings son uno de los principales elementos diferenciales del producto.

El sistema debe poder calcular:

### Player Rating

Valoración propia del jugador.

### Team Rating

Valoración propia del equipo.

### Power Ranking

Ranking basado en rendimiento reciente/histórico según el algoritmo definido.

### Form Index

Medición de forma reciente.

### Records

Récords individuales y colectivos.

### Milestones

Hitos estadísticos.

Los algoritmos deben ser independientes de la ingesta.

---

# 22. MEDIA Y REDES SOCIALES

La generación de contenido debe estar desacoplada del Core Domain.

El flujo conceptual es:

```text
Official Data
     ↓
Statistics
     ↓
Analytics
     ↓
Content
     ↓
Publication
     ↓
Instagram / X / Web / App
```

Instagram nunca debe consultar directamente la base de datos ni la fuente FEB.

---

# 23. INSTAGRAM

Instagram es uno de los primeros casos de uso del proyecto.

El objetivo es poder generar automáticamente publicaciones como:

* resultados;
* clasificación;
* MVP;
* jugador destacado;
* líderes;
* mejores actuaciones;
* rankings;
* récords;
* rachas;
* comparativas;
* estadísticas de jornada.

Pero el sistema de publicación debe ser un consumidor del Core Engine.

No debe convertirse en parte del Core Domain.

---

# 24. ARQUITECTURA EVOLUTIVA

La arquitectura debe ser evolutiva.

No se deben introducir tecnologías complejas únicamente por anticipar una escala futura.

La estrategia recomendada es:

### Fase inicial

* Python.
* Core Domain independiente.
* PostgreSQL.
* Repository pattern.
* Procesos de ingestión controlados.
* Tests.
* JSON contracts.
* almacenamiento raw sencillo.

### Fase de crecimiento

Introducir cuando exista una necesidad real:

* colas;
* cache;
* almacenamiento de objetos;
* procesamiento asíncrono;
* observabilidad avanzada.

### Fase de escala

Si el volumen y número de consumidores lo justifican:

* event backbone;
* Kafka u otra solución equivalente;
* OLAP especializado;
* procesamiento distribuido;
* infraestructura cloud más avanzada.

La arquitectura debe permitir esta evolución sin modificar las reglas fundamentales del dominio.

---

# 25. POSTGRESQL

PostgreSQL es la opción prevista para sustituir la persistencia inicial basada en SQLite.

SQLite se utilizó para validar el prototipo.

PostgreSQL será la persistencia principal del sistema cuando se implemente la capa de infraestructura.

Importante:

El dominio NO debe depender de PostgreSQL.

La arquitectura debe ser:

```text
Domain
  ↑
Application
  ↑
Repository Interface
  ↑
PostgreSQL Repository
```

Esto permitirá probar el dominio con repositorios en memoria.

---

# 26. TESTING

Los tests son parte fundamental del proyecto.

Se deben cubrir:

### Domain tests

* invariantes;
* transiciones;
* aggregates;
* value objects.

### Application tests

* Commands;
* Use Cases;
* Domain Events.

### Contract tests

Los comandos y eventos generados deben cumplir los JSON Schema oficiales.

### Property-based testing

Debe utilizarse cuando aporte valor para comprobar invariantes como:

* consistencia de parciales;
* consistencia de resultados;
* estados válidos;
* reglas de corrección.

---

# 27. PRINCIPIOS ARQUITECTÓNICOS

### 1. El dominio no conoce la infraestructura

El Core Domain no debe saber cómo se almacenan o transportan los datos.

### 2. FEB es una fuente externa

No debe contaminar el modelo interno.

### 3. Los contratos son explícitos

Los contextos se comunican mediante contratos definidos.

### 4. Los eventos representan hechos

No intenciones.

### 5. Los datos raw son reproducibles

Debe poder reprocesarse una fuente histórica.

### 6. Todo cálculo importante es versionable

Especialmente ratings y reglas.

### 7. Las correcciones son auditables

Nunca destruir silenciosamente información histórica.

### 8. Los consumidores están desacoplados

Instagram, web y móvil no forman parte del Core Domain.

### 9. Evitar sobreingeniería

La arquitectura debe evolucionar con las necesidades reales.

---

# 28. ESTADO ACTUAL

El proyecto ha completado conceptualmente:

* [x] Investigación inicial de FEB.
* [x] Prototipo de extracción.
* [x] Validación de extracción de partidos.
* [x] Extracción de datos estructurados.
* [x] Persistencia SQLite inicial.
* [x] Definición del dominio.
* [x] Ubiquitous Language.
* [x] Commands.
* [x] Domain Events.
* [x] JSON Schema v1.
* [x] Contract Matrix.
* [x] Bounded Context Map.
* [x] Aggregate Map.
* [x] Ownership Matrix.
* [x] Implementación inicial del Core Domain.
* [x] Repositorios en memoria.
* [x] Tests iniciales.

---

# 29. PRÓXIMO PASO

Antes de continuar con infraestructura debe completarse una auditoría del Core Domain.

El objetivo es comprobar:

* pureza del dominio;
* cumplimiento DDD;
* coherencia entre código y contratos;
* cobertura de tests;
* invariantes;
* idempotencia;
* correcciones;
* transiciones de Match;
* Contract Tests.

El resultado esperado será:

```text
CORE DOMAIN v1 — READY
```

Una vez conseguido:

```text
CORE DOMAIN
     ↓
PERSISTENCE LAYER
     ↓
POSTGRESQL
     ↓
INGESTION / NORMALIZER
     ↓
DATOS FEB REALES
```

---

# 30. LO QUE NO DEBEMOS HACER TODAVÍA

No introducir prematuramente:

* Kafka.
* Microservicios.
* Kubernetes.
* Redis.
* ClickHouse.
* S3 como dependencia del dominio.
* infraestructura cloud compleja.

Estas tecnologías pueden aparecer posteriormente si el volumen y los requisitos lo justifican.

La prioridad actual es construir un **Core Engine correcto, testeable y mantenible**.

---

# 31. VISIÓN FINAL

La arquitectura objetivo es:

```text
                    FEB
                     │
                     ▼
              ┌─────────────┐
              │   INGESTION │
              └──────┬──────┘
                     │
                     ▼
              ┌─────────────┐
              │ NORMALIZER  │
              └──────┬──────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │       CORE DOMAIN       │
        │                         │
        │ Match / Teams / Players │
        │ Rules / Stats           │
        │ Standings               │
        └────────────┬────────────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
       Ratings   Analytics    Records
          │          │          │
          └──────────┼──────────┘
                     ▼
              ┌─────────────┐
              │    MEDIA    │
              └──────┬──────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
       Instagram     Web       Mobile
```

El objetivo final no es crear un scraper de FEB.

El objetivo es construir una **plataforma de datos deportivos especializada en baloncesto español**, donde FEB sea inicialmente la principal fuente de datos y donde el Core Engine permita posteriormente crear múltiples productos y consumidores sobre una única fuente de verdad.

---

# 32. REGLA PARA FUTUROS DESARROLLADORES / AGENTES

Cualquier nuevo desarrollador o agente de IA que trabaje en este repositorio debe:

1. Leer este documento antes de modificar la arquitectura.
2. Leer `contracts/`.
3. Leer `bounded_context_map.md`.
4. Respetar los Aggregates y ownership definidos.
5. No introducir infraestructura dentro del dominio.
6. No modificar contratos existentes silenciosamente.
7. Versionar cualquier cambio incompatible.
8. No asumir que los endpoints internos de FEB son estables.
9. No convertir Instagram en una dependencia del Core.
10. Priorizar simplicidad y evolución frente a sobreingeniería.

Si existe una contradicción entre este documento y el código actual, **no asumir automáticamente que el código es correcto**.

Documentar primero la contradicción y determinar cuál debe ser la fuente de verdad.
