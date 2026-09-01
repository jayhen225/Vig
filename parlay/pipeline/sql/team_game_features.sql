WITH team_offense AS (
    SELECT 
        posteam AS team,
        season,
        week,
        game_id,
        COUNT(*) AS off_plays,
        ROUND(AVG(epa), 4) AS off_epa,
        ROUND(AVG(CASE WHEN play_type = 'pass' THEN epa END), 4) AS off_pass_epa,
        ROUND(AVG(CASE WHEN play_type = 'run' THEN epa END), 4) AS off_rush_epa,
        ROUND(SUM(CASE WHEN play_type = 'pass' THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS pass_rate
    FROM pbp_data
    WHERE play_type IN ('pass', 'run') AND posteam IS NOT NULL
    GROUP BY posteam, season, week, game_id
),
team_defense AS (
    SELECT
        defteam AS team,
        season,
        week,
        game_id,
        COUNT(*) AS def_plays,
        ROUND(AVG(epa), 4) AS def_epa,
        ROUND(AVG(CASE WHEN play_type = 'pass' THEN epa END), 4) AS def_pass_epa,
        ROUND(AVG(CASE WHEN play_type = 'run' THEN epa END), 4) AS def_rush_epa
    FROM pbp_data
    WHERE play_type IN ('pass', 'run') AND defteam IS NOT NULL
    GROUP BY defteam, season, week, game_id
),
game_scores AS (
    SELECT game_id, home_team, away_team, home_score, away_score
    FROM schedule_data
),
combined AS (
    SELECT
        o.team,
        o.season,
        o.week,
        o.game_id,
        o.off_plays,
        o.off_epa,
        o.off_pass_epa,
        o.off_rush_epa,
        o.pass_rate,
        d_opp.def_epa AS opp_def_epa,
        d_opp.def_pass_epa AS opp_def_pass_epa,
        d_opp.def_rush_epa AS opp_def_rush_epa,
        CASE WHEN g.home_team = o.team THEN 1 ELSE 0 END AS is_home,
        CASE WHEN g.home_team = o.team THEN g.home_score ELSE g.away_score END AS points_scored,
        CASE WHEN g.home_team = o.team THEN g.away_score ELSE g.home_score END AS points_allowed
    FROM team_offense o
    JOIN team_defense d_opp 
        ON o.game_id = d_opp.game_id AND o.team != d_opp.team
    JOIN game_scores g 
        ON o.game_id = g.game_id
),
league_averages AS (
    SELECT
        ROUND(AVG(off_epa), 4) AS league_off_epa,
        ROUND(AVG(off_pass_epa), 4) AS league_off_pass_epa,
        ROUND(AVG(off_rush_epa), 4) AS league_off_rush_epa,
        ROUND(AVG(pass_rate), 4) AS league_pass_rate,
        ROUND(AVG(opp_def_epa), 4) AS league_def_epa,
        ROUND(AVG(opp_def_pass_epa), 4) AS league_def_pass_epa,
        ROUND(AVG(opp_def_rush_epa), 4) AS league_def_rush_epa
    FROM combined
)
SELECT
    c.team,
    c.season,
    c.week,
    c.game_id,
    c.is_home,
    c.points_scored,
    c.points_allowed,
    c.off_epa,
    c.off_pass_epa,
    c.off_rush_epa,
    COALESCE(
        ROUND(AVG(c.off_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_off_epa
    ) AS rolling_off_epa,
    COALESCE(
        ROUND(AVG(c.off_pass_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_off_pass_epa
    ) AS rolling_off_pass_epa,
    COALESCE(
        ROUND(AVG(c.off_rush_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_off_rush_epa
    ) AS rolling_off_rush_epa,
    COALESCE(
        ROUND(AVG(c.pass_rate) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_pass_rate
    ) AS rolling_pass_rate,
    COALESCE(
        ROUND(AVG(c.opp_def_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_def_epa
    ) AS rolling_opp_def_epa,
    COALESCE(
        ROUND(AVG(c.opp_def_pass_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_def_pass_epa
    ) AS rolling_opp_def_pass_epa,
    COALESCE(
        ROUND(AVG(c.opp_def_rush_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_def_rush_epa
    ) AS rolling_opp_def_rush_epa
FROM combined c
CROSS JOIN league_averages la
ORDER BY c.season, c.week, c.team

