# Core Domain Audit - Risk Report

## Status
**NOT READY** (Fase 1 completada, pendiente de validación y correcciones).

## Domain Purity
**PASS**: No se detectan importaciones de infraestructura (BBDD, HTTP, colas, etc.) dentro del directorio `src/feb_score/domain/`.

## Static Audit - Problems Found

### 1. Discrepancia de Contratos (Contracts vs Handlers)
* **Archivo:** `src/feb_score/application/use_cases/handlers.py` vs `contracts/commands/finalize_match.v1.json`
* **Línea:** 149 (`handlers.py`)
* **Problema:** El handler de `FinalizeMatchCommand` extrae `finalized_at` del payload, pero el contrato JSON no define ese campo. Además, el contrato define `validation_context`, que el handler ignora. Por otro lado, no existe una implementación de validación de los JSON schemas en `src/feb_score/contracts` (solo hay un `__init__.py`).
* **Severidad:** **CRITICAL**
* **Impacto:** Un consumidor que envíe comandos basados en el contrato oficial fallará, o el sistema procesará mal los datos al asumir campos que no existen.
* **Solución Recomendada:** El contrato es probablemente la fuente correcta (schema versionado). Se debe alinear el handler para no esperar `finalized_at` del payload y utilizar `issued_at` o la fecha del sistema, e implementar validación de schema en `application/commands`.

### 2. Anemic Domain Model / Lógica de Negocio en Application Service
* **Archivo:** `src/feb_score/application/use_cases/handlers.py`
* **Línea:** 138-173 (`FinalizeMatchHandler`) y 412-457 (`ComputePlayerRatingHandler`)
* **Problema:** Los handlers están asumiendo responsabilidades del dominio. 
    * `FinalizeMatchHandler` instancia y emite eventos de dominio directamente (`MatchValidationStarted`, `MatchValidated`, `ValidationFailed`) en lugar de que el Aggregate `Match` orqueste este proceso interno.
    * `ComputePlayerRatingHandler` tiene lógica de negocio pura: determina si se alcanza un hito (`rating_value.value >= 80.0`) para emitir el evento `PlayerMilestoneReached`.
* **Severidad:** **HIGH**
* **Impacto:** Fuga de reglas de negocio a la capa de aplicación, dificultando el testing aislado del dominio y violando la encapsulación de DDD.
* **Solución Recomendada:** Mover la creación de eventos de finalización dentro del método `finalize()` de `Match`. Mover el cálculo del hito a un Domain Service o a un Factory Method en `PlayerRating`.

### 3. Aggregate Invariants Break & Weak Typing
* **Archivo:** `src/feb_score/domain/match/model.py`
* **Línea:** 243-275 (`apply_correction`)
* **Problema:** Se manipulan diccionarios crudos (`change.get("home_score")`) en lugar de usar Value Objects o Typed Commands. Peor aún, si los scores parciales (`periods`) no coinciden con los nuevos totales, se silencian/eliminan los periodos (`existing_periods = tuple()`) en lugar de rechazar la corrección.
* **Severidad:** **HIGH**
* **Impacto:** Si un administrador corrige un marcador pero olvida corregir los parciales, el sistema borra los parciales silenciosamente en lugar de devolver un error por inconsistencia.
* **Solución Recomendada:** La corrección debería estar fuertemente tipada. Si hay periodos pero no cuadran con el total, el Aggregate debe lanzar `InvalidCorrection` en lugar de borrar la información de forma silenciosa.

---

## Recomendaciones para Fase 3 (Selective Testing)

Basado en estos hallazgos, recomiendo ejecutar **ÚNICAMENTE** los siguientes tests (cuando pasemos a la Fase 3, para resolver los riesgos):

1. **Para resolver Riesgo 1 y 2 (Finalización):** Tests de `FinalizeMatchHandler` y `Match.finalize`.
2. **Para resolver Riesgo 2 (Ratings):** Tests de `ComputePlayerRatingHandler` y generación del rating.
3. **Para resolver Riesgo 3 (Correcciones):** Tests de `Match.apply_correction`.

---

## Test Results (Phase 3)

### Match Corrections
- **Test:** `tests/domain/test_match_correction_mismatch.py`
- **Resultado:** El test PASÓ confirmando el defecto.
- **Análisis:** Al aplicar una corrección (`update_score`) con un nuevo marcador que no concuerda con los periodos existentes, el Aggregate `Match` **elimina silenciosamente** los periodos en lugar de lanzar una excepción `InvalidCorrection`. El estado del Aggregate queda corrompido de cara a la integridad de los parciales, y la corrección no es abortada.
- **Conclusión:** Se verifica el Riesgo 3. Este es un problema arquitectónico importante porque la regla de negocio (invariante) de que los parciales deben sumar el total es eludida al borrar la información conflictiva.
