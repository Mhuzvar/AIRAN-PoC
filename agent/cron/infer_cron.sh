#!/bin/bash

STATE_FILE="/tmp/.tmp_watch_state"
LOCK_FILE="/tmp/.tmp_watch.lock"
LOG_FILE="/tmp/ayran_std.log"
ERR_LOG="/tmp/ayran_err.log"
PROMPT_COUNTER="/tmp/agent_counter.txt"
OUTPUT_DIR="/sandbox/agent_responses"
SESSION_ID_FILE="/tmp/session_id.txt"
#SESSION_ID=RANalyzer_agent
#PROMPT="/sandbox/cron_scripts/analysis_prompt.txt"
# hang check in seconds, set really high  and test before settling on a value
AGENT_TIMEOUT=270
SESSION_LIMIT=10

mkdir -p "$OUTPUT_DIR"

exec 200>"$LOCK_FILE"
flock -n 200 || exit 1

shopt -s nullglob
CURRENT=$(for f in /tmp/diagdata_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].csv; do
    basename "$f"
done)
shopt -u nullglob

if [ -f "$STATE_FILE" ]; then
    NEW_FILES=$(comm -13 <(sort "$STATE_FILE") <(echo "$CURRENT" | sort))
    if [ -n "$NEW_FILES" ]; then
        LATEST=$(echo "$NEW_FILES" | sed -E 's/^diagdata_([0-9]{14})\.csv$/\1 &/' | sort -n | tail -n 1 | cut -d' ' -f2)

        if [ -n "$LATEST" ]; then
            echo "$(date): New file detected (highest of $(echo "$NEW_FILES" | wc -l)): $LATEST" >> "$LOG_FILE"
            if (( $(<$PROMPT_COUNTER) < $SESSION_LIMIT )); then
                echo $(( $(<$PROMPT_COUNTER) + 1 )) > $PROMPT_COUNTER
                SESSION_ID=$(<"$SESSION_ID_FILE")
            else
                echo "1" > $PROMPT_COUNTER
                SESSION_ID="RANalyzer_agent$(date +%y%m%d%H%M)"
                echo $SESSION_ID > $SESSION_ID_FILE
            fi
            output_file="$OUTPUT_DIR/response_$(date +%y%m%d%H%M%S).json"
            timeout -k 30 "$AGENT_TIMEOUT" env NODE_NO_WARNINGS=1 openclaw agent \
                --agent main \
                --session-id $SESSION_ID \
                --json -m "/tmp/$LATEST" \
                2>>"$ERR_LOG" > "$output_file"

            agent_status=${PIPESTATUS[0]}
            if [ "$agent_status" -ne 0 ]; then
                echo "$(date): FAILED (agent exit $agent_status) processing $LATEST — see $ERR_LOG" >> "$LOG_FILE"
                rm -f "$output_file"
            else
                echo "$(date): Agent response saved to $output_file" >> "$LOG_FILE"
            fi

        fi
    fi
else
    echo "0" > $PROMPT_COUNTER
    echo "RANalyzer_agent$(date +%y%m%d%H%M)" > $SESSION_ID_FILE
fi

echo "$CURRENT" > "$STATE_FILE"