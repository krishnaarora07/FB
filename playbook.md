# FB Autonomous Football Manager Playbook

## Objective
Monitor football news daily within a 10-day cycle. Generate exactly ONE high-virality video (Score >= 8) per cycle. If no story hits 8 by Day 9, use the best story found and publish on Day 10.

## Required Skills
- `/youtube-video-research`
- `/video-generator`

## State Management
Read `job_state.json` from the `krishnaarora07/FB` repository to determine the current cycle status:
- `cycle_start_date`: The date the current 10-day cycle began.
- `video_published`: Boolean, whether a video has been generated in this cycle.
- `highest_score_so_far`: The highest virality score recorded in this cycle.
- `best_topic_so_far`: The topic associated with the highest score.

## Workflow
1. **Check Cooldown**: If `video_published` is true and we are within 10 days of `cycle_start_date`, log "In cooldown" and exit.
2. **Reset Cycle**: If more than 10 days have passed since `cycle_start_date`, reset `cycle_start_date` to today, set `video_published` to false, and clear scores.
3. **Research**: Use `/youtube-video-research` to find breaking football news, viral moments, and transfers from the last 24 hours.
4. **Score**: Evaluate news against the **Virality Meter** (1-10):
   - 1-3: Routine
   - 4-6: Interesting
   - 7-9: Major controversy/Shock
   - 10: Global headline
5. **Decision**:
   - If current score >= 8: Proceed to **Generation**.
   - If Day 10 of cycle: Use `best_topic_so_far` and proceed to **Generation**.
   - Otherwise: Update `highest_score_so_far` and `best_topic_so_far` if the new score is higher, then exit.
6. **Generation**:
   - Write a 130-150 word script (approx. 60s).
   - Follow `/video-generator` Phase 1-5 for visual planning.
   - Use HeyGen MCP `create_video_agent` to generate the video.
   - Update `job_state.json`: set `video_published` to true.
7. **Log & Sync**:
   - Update `logs/autonomous_job_log.md` and `topic_history.json`.
   - Push all changes (including `job_state.json`) to the `krishnaarora07/FB` GitHub repository.
