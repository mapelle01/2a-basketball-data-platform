Contract Matrix: Command -> Events -> Primary Consumers

1. CreateOrUpdateMatch -> emits MatchUpserted
   Consumers: Rules & Validation, Statistics, Admin

2. FinalizeMatch -> MatchValidationStarted, MatchValidated, MatchFinalized | ValidationFailed
   Consumers: Statistics (canonicalization), Ratings, Media, Publication

3. ProposeCorrection -> CorrectionProposed
   Consumers: Administration, Core (locks)

4. ApproveCorrection -> CorrectionApproved, MatchUpdatedByCorrection
   Consumers: Statistics (recompute), Ratings, Media

5. RegisterPlayerToSquad -> PlayerRegistered
   Consumers: Rules & Validation, Core Domain

6. GenerateStandingSnapshot -> StandingSnapshotGenerated
   Consumers: Media, API, Admin

7. GenerateLeaderboard -> LeaderboardGenerated
   Consumers: Media, API, Analytics

8. ComputePlayerRating -> PlayerRatingComputed, possible PlayerMilestoneReached
   Consumers: Media, API, Publication

9. CreatePublication -> PublicationCreated
   Consumers: Media & Publishing, Admin

10. BackfillSeason -> SeasonBackfillStarted, SeasonBackfillCompleted
   Consumers: Statistics, Ratings, Admin

Error/Alerts: ValidationFailed, CorrectionRejected, DomainAlert — consumers: Admin, Monitoring, Ops

Note: This matrix is conceptual; events are versioned and consumers must declare supported versions.
