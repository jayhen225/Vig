SELECT
    p.gsis_id,
    p.display_name,
    p.position_group,
    CASE
        WHEN p.draft_round IN (1, 2) THEN 'Rounds 1-2'
        WHEN p.draft_round IN (3, 4) THEN 'Rounds 3-4'
        WHEN p.draft_round IN (5, 6, 7) THEN 'Rounds 5-7'
        WHEN p.draft_round IS NULL THEN 'Undrafted'
        ELSE 'Unknown'
    END AS draft_tier,
    pbp.game_id,
    pbp.season,
    pbp.week,
    COUNT(*) AS player_carries,
    team_attempts.total_rush_attempts,
    ROUND(COUNT(*) * 1.0 / team_attempts.total_rush_attempts, 4) AS carry_share
FROM pbp_data pbp
JOIN players_data p ON pbp.rusher_player_id = p.gsis_id
JOIN (
    SELECT game_id, posteam, COUNT(*) AS total_rush_attempts
    FROM pbp_data
    WHERE play_type = 'run'
    GROUP BY game_id, posteam
) team_attempts ON pbp.game_id = team_attempts.game_id AND pbp.posteam = team_attempts.posteam
WHERE pbp.play_type = 'run'
  AND p.position_group IN ('RB')
  AND pbp.rusher_player_id IS NOT NULL
GROUP BY
    p.gsis_id,
    p.display_name,
    p.position_group,
    draft_tier,
    pbp.game_id,
    pbp.season,
    pbp.week,
    team_attempts.total_rush_attempts
ORDER BY pbp.season, pbp.week, carry_share DESC
;