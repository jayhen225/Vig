-- Per-player rolling usage over the last 6 games.
-- Used by Layer 1 (recency weighting) to shift the model's center
-- toward current role rather than career average.
--
-- Returns one row per player per game with:
--   career_avg: target/carry share across all prior games
--   recent_avg: target/carry share across the last 6 games only
--   recent_games: how many of the last 6 games had data
--
-- The recency weight is computed in Python based on how much
-- recent_avg diverges from career_avg and how many recent games exist.

-- TARGET SHARE (receiving usage for WR/TE/RB)
SELECT
    'target_share' AS metric,
    p.gsis_id,
    p.display_name,
    p.position_group,
    pbp.game_id,
    pbp.season,
    pbp.week,
    -- Per-game target share (this game)
    ROUND(COUNT(*) * 1.0 / team_att.total_pass_attempts, 4) AS game_usage,
    -- Career rolling average (all prior games)
    ROUND(AVG(COUNT(*) * 1.0 / team_att.total_pass_attempts) OVER (
        PARTITION BY p.gsis_id
        ORDER BY pbp.season, pbp.week
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ), 4) AS career_avg,
    -- Recent rolling average (last 6 games only)
    ROUND(AVG(COUNT(*) * 1.0 / team_att.total_pass_attempts) OVER (
        PARTITION BY p.gsis_id
        ORDER BY pbp.season, pbp.week
        ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
    ), 4) AS recent_avg,
    -- How many of the last 6 game slots had data
    COUNT(COUNT(*)) OVER (
        PARTITION BY p.gsis_id
        ORDER BY pbp.season, pbp.week
        ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
    ) AS recent_games
FROM pbp_data pbp
JOIN players_data p ON pbp.receiver_player_id = p.gsis_id
JOIN (
    SELECT game_id, posteam, COUNT(*) AS total_pass_attempts
    FROM pbp_data
    WHERE play_type = 'pass'
    GROUP BY game_id, posteam
) team_att ON pbp.game_id = team_att.game_id AND pbp.posteam = team_att.posteam
WHERE pbp.play_type = 'pass'
  AND p.position_group IN ('WR', 'TE', 'RB')
  AND pbp.receiver_player_id IS NOT NULL
GROUP BY p.gsis_id, p.display_name, p.position_group,
         pbp.game_id, pbp.season, pbp.week, team_att.total_pass_attempts

UNION ALL

-- CARRY SHARE (rushing usage for RB)
SELECT
    'carry_share' AS metric,
    p.gsis_id,
    p.display_name,
    p.position_group,
    pbp.game_id,
    pbp.season,
    pbp.week,
    ROUND(COUNT(*) * 1.0 / team_att.total_rush_attempts, 4) AS game_usage,
    ROUND(AVG(COUNT(*) * 1.0 / team_att.total_rush_attempts) OVER (
        PARTITION BY p.gsis_id
        ORDER BY pbp.season, pbp.week
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ), 4) AS career_avg,
    ROUND(AVG(COUNT(*) * 1.0 / team_att.total_rush_attempts) OVER (
        PARTITION BY p.gsis_id
        ORDER BY pbp.season, pbp.week
        ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
    ), 4) AS recent_avg,
    COUNT(COUNT(*)) OVER (
        PARTITION BY p.gsis_id
        ORDER BY pbp.season, pbp.week
        ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
    ) AS recent_games
FROM pbp_data pbp
JOIN players_data p ON pbp.rusher_player_id = p.gsis_id
JOIN (
    SELECT game_id, posteam, COUNT(*) AS total_rush_attempts
    FROM pbp_data
    WHERE play_type = 'run'
    GROUP BY game_id, posteam
) team_att ON pbp.game_id = team_att.game_id AND pbp.posteam = team_att.posteam
WHERE pbp.play_type = 'run'
  AND p.position_group = 'RB'
  AND pbp.rusher_player_id IS NOT NULL
GROUP BY p.gsis_id, p.display_name, p.position_group,
         pbp.game_id, pbp.season, pbp.week, team_att.total_rush_attempts

ORDER BY metric, gsis_id, season, week