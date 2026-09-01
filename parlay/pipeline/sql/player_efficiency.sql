-- Per-player per-game efficiency stats for the simulator's efficiency layer.
-- Three metrics, each computed at the player-game level:
--   1. Yards per target (WR/TE/RB) — receiving_yards / targets per game
--   2. Yards per carry (RB) — rushing_yards / carries per game
--   3. Yards per attempt (QB) — passing_yards / attempts per game
--
-- Each row includes position_group for shrinkage toward positional averages.
-- Only games where the player had at least 1 target/carry/attempt are included.

-- RECEIVING EFFICIENCY: yards per target
SELECT
    'yards_per_target' AS metric,
    p.gsis_id,
    p.display_name,
    p.position_group,
    pbp.game_id,
    pbp.season,
    pbp.week,
    COUNT(*) AS opportunities,
        SUM(COALESCE(pbp.receiving_yards, 0)) AS total_yards,
    ROUND(SUM(COALESCE(pbp.receiving_yards, 0)) * 1.0 / COUNT(*), 2) AS yards_per_opportunity
FROM pbp_data pbp
JOIN players_data p ON pbp.receiver_player_id = p.gsis_id
WHERE pbp.play_type = 'pass'
  AND pbp.receiver_player_id IS NOT NULL
  AND pbp.play_type = 'pass'
  AND p.position_group IN ('WR', 'TE', 'RB')
GROUP BY p.gsis_id, p.display_name, p.position_group, pbp.game_id, pbp.season, pbp.week

UNION ALL

-- RUSHING EFFICIENCY: yards per carry
SELECT
    'yards_per_carry' AS metric,
    p.gsis_id,
    p.display_name,
    p.position_group,
    pbp.game_id,
    pbp.season,
    pbp.week,
    COUNT(*) AS opportunities,
    SUM(pbp.rushing_yards) AS total_yards,
    ROUND(SUM(pbp.rushing_yards) * 1.0 / COUNT(*), 2) AS yards_per_opportunity
FROM pbp_data pbp
JOIN players_data p ON pbp.rusher_player_id = p.gsis_id
WHERE pbp.play_type = 'run'
  AND pbp.rusher_player_id IS NOT NULL
  AND pbp.rushing_yards IS NOT NULL
  AND p.position_group = 'RB'
GROUP BY p.gsis_id, p.display_name, p.position_group, pbp.game_id, pbp.season, pbp.week

UNION ALL

-- PASSING EFFICIENCY: yards per attempt (includes incompletes as 0)
SELECT
    'yards_per_attempt' AS metric,
    p.gsis_id,
    p.display_name,
    p.position_group,
    pbp.game_id,
    pbp.season,
    pbp.week,
    COUNT(*) AS opportunities,
    SUM(COALESCE(pbp.passing_yards, 0)) AS total_yards,
    ROUND(SUM(COALESCE(pbp.passing_yards, 0)) * 1.0 / COUNT(*), 2) AS yards_per_opportunity
FROM pbp_data pbp
JOIN players_data p ON pbp.passer_player_id = p.gsis_id
WHERE pbp.play_type = 'pass'
  AND pbp.passer_player_id IS NOT NULL
  AND p.position_group = 'QB'
GROUP BY p.gsis_id, p.display_name, p.position_group, pbp.game_id, pbp.season, pbp.week

ORDER BY metric, season, week, gsis_id