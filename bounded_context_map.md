# Bounded Context Map + Domain Model

Este documento define la arquitectura conceptual del dominio de la plataforma FEB, basada exclusivamente en los contratos y eventos v1 ya definidos. No contiene infraestructura, código ni decisiones tecnológicas de implementación.

## 1. Bounded Contexts definitivos

Se establecen los siguientes bounded contexts. No se crean contextos solo por su nombre: cada uno tiene responsabilidad delimitada y un lenguaje propio.

1. Match Management & Identity
2. Rules & Competition
3. Statistics
4. Standings & Leaderboards
5. Ratings & Analytics
6. Media & Content
7. Administration & Audit

### Decisiones de contexto
- `Match Management & Identity` mantiene la propiedad de las entidades de identidad y del partido. Es el contexto central del dominio.
- `Rules & Competition` es el contexto de políticas y validación de reglas. No contiene estadísticas ni publicaciones.
- `Statistics` es el contexto de métricas de partido y snapshots intermedios. No publica contenido ni ratings.
- `Standings & Leaderboards` es el contexto de clasificación y listas ordenadas derivadas. Es distinto a Statistics para separar el cálculo de métricas del formato de entrega de ranking.
- `Ratings & Analytics` contiene métricas de valor añadido y detección de records/milestones. No gestiona partidos, solo consume datos canonizados.
- `Media & Content` gestiona publicaciones y plantillas. Consume resultados y métricas finales, pero no muta el dominio deportivo.
- `Administration & Audit` gestiona correcciones, aprobaciones y trazabilidad. Actúa como guardián de cambios manuales.

## 2. Responsabilidad de cada contexto

### 2.1 Match Management & Identity

**Propósito**
- Gestión de identidad canónica y del ciclo de vida de los partidos.
- Registrar Match provicionales y mantener entidades deportivas auténticas.

**Entidades principales**
- Match
- Team
- Player
- Squad / TeamRegistration
- PlayerRegistration
- Venue
- Official
- Source / Provenance

**Aggregate Roots**
- MatchAggregate (Match)
- TeamAggregate (TeamRegistration / Squad)
- PlayerAggregate (Player)

**Comandos que recibe**
- CreateOrUpdateMatch
- RegisterPlayerToSquad
- ApproveCorrection (a través de Administration)

**Eventos que publica**
- MatchUpserted
- MatchUpdatedByCorrection
- PlayerRegistered
- CorrectionApproved

**Datos que posee**
- Identidad de Match, Team, Player
- Alineaciones históricas de squads
- Referencias canónicas de partidos y fuentes
- Estado de partido: PROVISIONAL, SCHEDULED, IN_PLAY, FINALIZED, CANCELLED

**Datos que NO posee**
- Cálculos de standings, rating o power ranking
- Publicaciones o plantillas de contenido
- Liderboards derivados
- Reglas de desempate completas

**Propietario**
- El contexto es propietario de `Match`, `Team`, `Player`, `Squad` y `PlayerRegistration`.

### 2.2 Rules & Competition

**Propósito**
- Definir y aplicar reglas de competencia, elegibilidad y finalización.
- Encapsular el lenguaje de las reglas de competición FEB.

**Entidades principales**
- Competition
- Season
- Round
- RuleSet
- EligibilityPolicy
- TieBreakPolicy

**Aggregate Roots**
- CompetitionAggregate (Competition + Season + Round + RuleSet)

**Comandos que recibe**
- FinalizeMatch
- GenerateStandingSnapshot
- GenerateLeaderboard

**Eventos que publica**
- MatchValidationStarted
- MatchValidated
- ValidationFailed
- StandingSnapshotGenerated
- LeaderboardGenerated

**Datos que posee**
- Reglas de competición por Season
- Versiones de reglas y políticas de desempate
- Condiciones de elegibilidad de jugadores y squads

**Datos que NO posee**
- Estadísticas de partido detalladas
- Rating y milestones
- Publicaciones
- Correcciones manuales concretas

**Propietario**
- El contexto es propietario de `Competition`, `Season`, `Round` y la semántica de las reglas de validación.

### 2.3 Statistics

**Propósito**
- Transformar partidos finalizados en métricas deportivas exactas.
- Generar datos de PlayerStats y TeamStats que otros contextos consumen.

**Entidades principales**
- PlayerStats
- TeamStats
- MatchEvent (estadístico)
- Snapshot parcial de estadísticas

**Aggregate Roots**
- MatchAggregate (propietario de stats dentro del mismo aggregate)

**Comandos que recibe**
- MatchFinalized
- MatchUpdatedByCorrection
- SeasonBackfillStarted

**Eventos que publica**
- (no se añaden eventos de infraestructura; se presupone que Stats produce datos canónicos para el siguiente contexto a través de contrato)
- PlayerRatingComputed está consumido más adelante, pero no inventamos un evento adicional aquí.

**Datos que posee**
- Estadísticas de partido desglosadas por jugador y equipo
- Eventos de partido con detalles de incidentes
- Versionado de datos de stats si el partido cambia

**Datos que NO posee**
- Tablas de clasificación ordenadas
- Power Rankings ni FormIndex
- Publicación de contenido
- Política de corrección de reglas

**Propietario**
- `Statistics` es propietario de `PlayerStats`, `TeamStats` y de la representación precisa de métricas de partido.

### 2.4 Standings & Leaderboards

**Propósito**
- Producir clasificaciones y leaderboards a partir de estadísticas finalizadas.
- Mantener snapshots de standings y rankings.

**Entidades principales**
- StandingSnapshot
- StandingEntry
- Leaderboard
- LeaderboardEntry

**Aggregate Roots**
- StandingAggregate (StandingSnapshot)
- LeaderboardAggregate (Leaderboard)

**Comandos que recibe**
- GenerateStandingSnapshot
- GenerateLeaderboard

**Eventos que publica**
- StandingSnapshotGenerated
- LeaderboardGenerated

**Datos que posee**
- Tablas de clasificación inmutables
- Leaderboards ordenados por categoría
- Versiones de snapshots y reglas asociadas

**Datos que NO posee**
- Datos fuente de partido bruto
- Ratings derivados
- Contenido o plantillas

**Propietario**
- `Standings & Leaderboards` es propietario de `Standing` y `Leaderboard`.

### 2.5 Ratings & Analytics

**Propósito**
- Calcular métricas de valor agregado: ratings, power rankings, form index, records y milestones.
- Mantener la lógica de análisis y versionado de métricas avanzadas.

**Entidades principales**
- PlayerRating
- TeamRating
- PowerRanking
- FormIndex
- Record
- Milestone

**Aggregate Roots**
- RatingAggregate (RatingSeries / PlayerRating)
- RecordAggregate (Record)
- MilestoneAggregate (Milestone)

**Comandos que recibe**
- ComputePlayerRating
- BackfillSeason

**Eventos que publica**
- PlayerRatingComputed
- PlayerMilestoneReached
- SeasonBackfillStarted
- SeasonBackfillCompleted

**Datos que posee**
- Valores de rating versionados
- Historial de records y milestones
- Políticas de cálculo de analytics

**Datos que NO posee**
- Identidad de partidos o jugadores (solo referencias externas)
- Detalles de match beyond canonical stats
- Publicaciones

**Propietario**
- `Ratings & Analytics` es propietario de `PlayerRating`, `TeamRating`, `PowerRanking`, `FormIndex`, `Record`, `Milestone`.

### 2.6 Media & Content

**Propósito**
- Generar artefactos de contenido reproducibles a partir de datos canónicos.
- Gestionar el workflow de publicación y plantillas.

**Entidades principales**
- Publication
- ContentTemplate
- ImageTemplate
- PublicationPreview

**Aggregate Roots**
- PublicationAggregate (Publication)

**Comandos que recibe**
- CreatePublication

**Eventos que publica**
- PublicationCreated

**Datos que posee**
- Definiciones de plantillas y layouts
- Estado del contenido (DRAFT, SCHEDULED, PUBLISHED)
- Referencias a snapshots y match ids

**Datos que NO posee**
- Resultados de partidos directos (solo referencias)
- Estadísticas internas de partido
- Reglas de competición
- Correcciones manuales de dominio

**Propietario**
- `Media & Content` es propietario de `Publication` y `Template`.

### 2.7 Administration & Audit

**Propósito**
- Gestionar la gobernanza de cambios manuales, aprobaciones y auditoría.
- Registrar trazabilidad de quién hace qué y por qué.

**Entidades principales**
- CorrectionProposal
- AuditEntry
- User / Actor
- Approval

**Aggregate Roots**
- CorrectionAggregate (CorrectionProposal)
- AuditAggregate (AuditEntry)

**Comandos que recibe**
- ProposeCorrection
- ApproveCorrection

**Eventos que publica**
- CorrectionProposed
- CorrectionApproved
- CorrectionRejected

**Datos que posee**
- Historial completo de propuestas de corrección
- Estado de aprobación y razones
- Trazabilidad de actor/motivo

**Datos que NO posee**
- Resultados de partido directos
- Ratings o leaderboards
- Publicaciones de contenido

**Propietario**
- `Administration & Audit` es propietario de `CorrectionProposal` y `AuditEntry`.

## 3. Context Map

Relaciones de dependencia entre contextos:

- `Match Management & Identity` → `Statistics`
  - Upstream: Match Management
  - Downstream: Statistics
  - Published Language: MatchCanonicalDTO / MatchFinalized contract

- `Match Management & Identity` → `Rules & Competition`
  - Customer/Supplier: Rules consume Match references for validation.
  - Published Language: MatchValidationRequest

- `Rules & Competition` → `Statistics`
  - Upstream: Rules produce validation outcomes.
  - Downstream: Statistics consumes MatchFinalized / ValidationFailed.
  - Published Language: MatchFinalized, ValidationFailed

- `Statistics` → `Standings & Leaderboards`
  - Upstream: Statistics
  - Downstream: Standings & Leaderboards
  - Published Language: CanonicalStatsDTO

- `Standings & Leaderboards` → `Ratings & Analytics`
  - Customer/Supplier: Ratings consumes ranking snapshots and leaderboard results.
  - Published Language: StandingSnapshotRef / LeaderboardRef

- `Ratings & Analytics` → `Media & Content`
  - Customer/Supplier: Media consumes analytics outputs.
  - Published Language: AnalyticsReportRef

- `Administration & Audit` → `Match Management & Identity`
  - Customer/Supplier: Administration approves corrections that mutate Match.
  - Published Language: CorrectionApproved, CorrectionRejected

- `Administration & Audit` → `Rules & Competition`
  - Customer/Supplier: corrections may require revalidation.
  - Published Language: CorrectionApproved

Context map visual (conceptual):

Match Management & Identity
  ↓
Rules & Competition
  ↓
Statistics
  ↓
Standings & Leaderboards
  ↓
Ratings & Analytics
  ↓
Media & Content

Administration & Audit
  ↘
   ↳ Match Management & Identity
   ↳ Rules & Competition

## 4. Regla fundamental

Un contexto NO puede acceder directamente al modelo interno de otro contexto.

- `Ratings & Analytics` no accede a `MatchAggregate` interno.
- `Media & Content` no accede a la estructura interna de `PlayerStats` o `Match`.
- `Standings & Leaderboards` no accede a los modelos internos de `Statistics`, solo a contratos estabilizados.

Esta regla se aplica mediante contratos públicos formales (DTOs/eventos) entre contextos. Cada contexto consume únicamente los eventos y referencias publicados por su upstream, no la representación interna del upstream.

## 5. Anti-Corruption Layers (ACL)

ACLs necesarias y su rol transformador:

1. `FEB → Match Management` ACL
   - Traduce datos de origen FEB a los contratos de dominio `CreateOrUpdateMatch`.
   - Normaliza nombres de equipos/jugadores, convierte IDs externos y marca la procedencia.
   - Garantiza que el dominio no importa la forma exacta de la fuente.

2. `Match → Statistics` ACL
   - Traduce `MatchFinalized` y `MatchUpdatedByCorrection` a `CanonicalStatsDTO`.
   - Filtra sólo datos finalizados y valida que el payload respete los acuerdos de stat fields.

3. `Statistics → Ratings` ACL
   - Traduce métricas de estadísticas a `PlayerRating` inputs.
   - Aplica transformaciones de dominio: agrega sólo datos elegibles, versiona reglas de cálculo.

4. `Analytics → Media` ACL
   - Traduce `PlayerMilestoneReached`, `StandingSnapshotGenerated`, `LeaderboardGenerated` y `PlayerRatingComputed` a referencias y datos de contenido seguros.
   - Normaliza etiquetas de plantilla y score cards.

5. `Administration → Core Domain` ACL
   - Traduce `CorrectionApproved` a comandos internos de Match Management.
   - Asegura que la corrección preserva historial y no inyecta reglas de validación propias.

## 6. Aggregates principales

### 6.1 MatchAggregate

- Aggregate Root: `Match`
- Entidades internas: `MatchEvent`, `TeamStats`, `PlayerStats`, `Venue` (referencia), `Official` (referencia)
- Value Objects: `ScoreSummary`, `Period`, `SourceRef`
- Invariantes:
  - No se puede finalizar dos veces.
  - Los scores totales deben ser coherentes con los parciales.
  - Un match solo puede pasar a FINALIZED si las reglas de `Rules & Competition` lo permiten.
- Comandos permitidos:
  - CreateOrUpdateMatch
  - ApproveCorrection (aplica correcciones)
  - FinalizeMatch (dispara validación)

### 6.2 PlayerAggregate

- Aggregate Root: `Player`
- Entidades internas: `PlayerRegistration` (histórica), `PlayerIdentityMetadata`
- Value Objects: `Nationality`, `Height`, `Position`
- Invariantes:
  - Un player external_id es la identidad canónica.
  - No puede haber dos registros de player con el mismo external_id.
- Comandos permitidos:
  - RegisterPlayerToSquad
  - (correcciones de nombre/datos por administración, si se modela)

### 6.3 TeamAggregate

- Aggregate Root: `TeamRegistration` / `Squad`
- Entidades internas: `PlayerRegistration`, `CoachAssignment`
- Value Objects: `TeamIdentity`, `SeasonMembership`
- Invariantes:
  - Un player solo puede ser asignado a un squad válido para la season.
  - Un squad no puede tener dorsales duplicados sin permitirlo.
- Comandos permitidos:
  - RegisterPlayerToSquad

### 6.4 CompetitionAggregate

- Aggregate Root: `Competition`
- Entidades internas: `Season`, `Round`, `RuleSet`
- Value Objects: `CompetitionCode`, `TieBreakPolicy`
- Invariantes:
  - Una Season pertenece a una sola Competition.
  - Las reglas de desempate son consistentes para la season.
- Comandos permitidos:
  - GenerateStandingSnapshot
  - GenerateLeaderboard

### 6.5 StandingAggregate

- Aggregate Root: `StandingSnapshot`
- Entidades internas: `StandingEntry`
- Value Objects: `SnapshotMetadata`
- Invariantes:
  - El snapshot es inmutable una vez generado.
  - Todas las entradas en el snapshot corresponden a matches FINALIZED hasta `as_of`.
- Comandos permitidos:
  - GenerateStandingSnapshot

### 6.6 RatingAggregate

- Aggregate Root: `RatingSeries` / `PlayerRating`
- Entidades internas: `RatingSnapshot`, `Milestone`
- Value Objects: `RatingVersion`, `CalculationWindow`
- Invariantes:
  - Rating sólo se calcula sobre datos validados.
  - Cada snapshot incluye `rating_version` y `calculated_at`.
- Comandos permitidos:
  - ComputePlayerRating

### 6.7 PublicationAggregate

- Aggregate Root: `Publication`
- Entidades internas: `PublicationReference`, `MediaAsset`
- Value Objects: `PublicationStatus`, `TemplateReference`
- Invariantes:
  - Una publicación referencia snapshots inmutables.
  - El estado avanza en el workflow (DRAFT → SCHEDULED → PUBLISHED).
- Comandos permitidos:
  - CreatePublication

### 6.8 CorrectionAggregate

- Aggregate Root: `CorrectionProposal`
- Entidades internas: `Approval`, `AuditEntry`
- Value Objects: `CorrectionStatus`, `CorrectionDiff`
- Invariantes:
  - Una propuesta no puede ser aprobada si no tiene `reason` y `proposed_by`.
  - Las acciones aprobadas deben conservar `previous_version` y `new_version`.
- Comandos permitidos:
  - ProposeCorrection
  - ApproveCorrection

### 6.9 Qué NO es Aggregate

- `Period` debe ser value object dentro de Match.
- `StandingEntry` debe ser entidad interna de `StandingSnapshot`, no root.
- `LeaderboardEntry` debe ser entidad interna de `Leaderboard`.
- `SourceRef` es value object.
- `PublicationPreview` es value object dentro de `Publication`.

## 7. Ownership Matrix

| Concepto | Contexto propietario | Aggregate Root |
|---|---|---|
| Match | Match Management & Identity | MatchAggregate |
| Player | Match Management & Identity | PlayerAggregate |
| Team | Match Management & Identity | TeamAggregate |
| Squad / PlayerRegistration | Match Management & Identity | TeamAggregate |
| Venue | Match Management & Identity | MatchAggregate (referencia) |
| Official | Match Management & Identity | MatchAggregate (referencia) |
| Competition | Rules & Competition | CompetitionAggregate |
| Season | Rules & Competition | CompetitionAggregate |
| Round | Rules & Competition | CompetitionAggregate |
| RuleSet / TieBreakPolicy | Rules & Competition | CompetitionAggregate |
| PlayerStats | Statistics | MatchAggregate (stats portion) |
| TeamStats | Statistics | MatchAggregate (stats portion) |
| MatchEvent | Statistics | MatchAggregate (stats portion) |
| Standing | Standings & Leaderboards | StandingAggregate |
| Leaderboard | Standings & Leaderboards | LeaderboardAggregate |
| PlayerRating | Ratings & Analytics | RatingAggregate |
| TeamRating | Ratings & Analytics | RatingAggregate |
| PowerRanking | Ratings & Analytics | RatingAggregate |
| FormIndex | Ratings & Analytics | RatingAggregate |
| Record | Ratings & Analytics | RecordAggregate |
| Milestone | Ratings & Analytics | MilestoneAggregate |
| Publication | Media & Content | PublicationAggregate |
| ContentTemplate | Media & Content | PublicationAggregate |
| CorrectionProposal | Administration & Audit | CorrectionAggregate |
| AuditEntry | Administration & Audit | CorrectionAggregate |

## 8. Flujos principales

### 8.1 Partido nuevo

1. `FEB` → `ACL` → `Match Management`
   - Se transforma el origen FEB a `CreateOrUpdateMatch`.
2. `Match Management` crea/actualiza el `MatchAggregate` y publica `MatchUpserted`.
3. `Rules & Competition` recibe `MatchUpserted`, aplica reglas y, cuando se solicita, inicia `FinalizeMatch`.
4. Si la validación pasa, `Rules & Competition` publica `MatchFinalized`.
5. `Statistics` consume `MatchFinalized`, genera métricas canónicas de `PlayerStats` y `TeamStats`.
6. `Standings & Leaderboards` consume estadísticas y genera `StandingSnapshotGenerated` y `LeaderboardGenerated`.
7. `Ratings & Analytics` consume snapshots y calcula `PlayerRatingComputed` y `PlayerMilestoneReached`.
8. `Analytics` entrega datos a `Media & Content` para la generación de publicaciones.

### 8.2 Corrección

1. `Administration` recibe `ProposeCorrection`.
2. `Administration` publica `CorrectionProposed`.
3. Si se aprueba, `Administration` recibe `ApproveCorrection` y publica `CorrectionApproved`.
4. `Match Management` aplica la corrección y publica `MatchUpdatedByCorrection`.
5. `Statistics` consume `MatchUpdatedByCorrection`, re-perfila stats.
6. `Standings & Leaderboards` y `Ratings & Analytics` recomputan usando los nuevos datos.
7. `Media & Content` puede invalidar o regenerar publicaciones si es necesario.

### 8.3 Generación de contenido

1. `Ratings & Analytics` genera eventos como `PlayerMilestoneReached` y `PlayerRatingComputed`.
2. `Media & Content` consume estos eventos y crea `Publication` mediante `CreatePublication`.
3. `Media & Content` publica `PublicationCreated`.
4. `Administration` puede usar auditoría para rastrear quién aprobó la publicación si se habilita.

## 9. Dependencias prohibidas

Quedan explícitamente prohibidas las siguientes dependencias directas entre contextos:

- `Media & Content` → `Match Management` o `MatchAggregate` interno.
- `Ratings & Analytics` → `MatchAggregate` interno.
- `Standings & Leaderboards` → modelos internos de `Statistics`.
- `Administration & Audit` → lecturas directas del modelo interno de `Ratings & Analytics` para corregir datos.
- `Ratings & Analytics` → `FEB API` o fuente externa de FEB sin pasar por ACL.
- `Match Management & Identity` → `Standings & Leaderboards` para escribir resultados.
- Cualquier contexto no debe acceder a la implementación interna de otro contexto; solo a sus contratos publicados.

## 10. Decisiones cerradas

- `Match Management & Identity` es el contexto dueño de la identidad canónica y del ciclo de vida de partidos.
- `Rules & Competition` es dueño de las políticas de finalización y desempate.
- `Statistics` es dueño de los datos de PlayerStats y TeamStats.
- `Standings & Leaderboards` es dueño de clasificación y leaderboards.
- `Ratings & Analytics` es dueño de ratings, power rankings y milestones.
- `Media & Content` es dueño de publicaciones y templates.
- `Administration & Audit` es dueño de correcciones y trazabilidad.
- No se permiten dependencias directas entre contextos, solo contratos y eventos publicados.
- El lenguaje publicado entre contextos está cerrado a los contratos v1 definidos.
- No se introducen eventos de infraestructura para cubrir el dominio.

## 11. Decisiones pendientes

- Definir si `Standings & Leaderboards` debe ser un único contexto o dos contextos separados si la complejidad de leaderboards crece mucho. Por ahora queda unido por afinidad funcional.
- Determinar el nivel de detalle exacto de los contratos de `CanonicalStatsDTO` entre `Statistics` y `Ratings`, sin introducir aún otro evento oficial.
- Acordar la política de versiones de reglas concretas dentro de `Rules & Competition` en la práctica: ¿se versionan por season o por evento de snapshot? Esto está pendiente de definición operativa.
- Decidir si algunos tipos de corrección (p.ej. cambios de player metadata vs score) requieren contextos adicionales o si quedan gestionados íntegramente por `Administration & Audit`.

---

Este documento es la especificación conceptual del Core Domain. La siguiente fase será usarlo como base para diseñar los modelos internos y el flujo de comandos/eventos dentro de cada bounded context.
