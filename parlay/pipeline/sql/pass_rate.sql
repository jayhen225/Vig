SELECT
    posteam AS team,
    season,
    game_id,
    week,
    SUM(CASE WHEN play_type = 'pass' THEN 1 ELSE 0 END) AS pass_plays,
    SUM(CASE WHEN play_type IN ('pass', 'run') THEN 1 ELSE 0 END) AS total_plays,
    ROUND(SUM(CASE WHEN play_type = 'pass' THEN 1 ELSE 0 END) * 1.0 /
          SUM(CASE WHEN play_type IN ('pass', 'run') THEN 1 ELSE 0 END), 4) AS pass_rate
FROM pbp_data
WHERE play_type IN ('pass', 'run')
  AND posteam IS NOT NULL
GROUP BY posteam, season, game_id, week
ORDER BY season, week, posteam