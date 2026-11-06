"""Run the recorded campaign preparation demo."""
import argparse
import json
import sys

from campaign_agent.agent.run import AgentRuntime, DEMO_REQUEST


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", help="Resume a previously saved run ID.")
    args = parser.parse_args()
    runtime = AgentRuntime()
    run_id = args.resume or runtime.start(DEMO_REQUEST)
    print(f"Run ID: {run_id}", file=sys.stderr, flush=True)
    print(json.dumps(runtime.resume(run_id), indent=2))


if __name__ == "__main__":
    main()
