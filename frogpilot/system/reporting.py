import json
import time
import uuid

from openpilot.frogpilot.common.frogpilot_api import API_VERSION
from openpilot.frogpilot.common import frogpilot_paths, frogpilot_variables

def capture_report(issue_reported, frogpilot_toggles, frogpilot_api):
  report_data = json.loads(issue_reported)

  error_content = "No error log found."
  error_file_path = frogpilot_paths.ERROR_FILE_PATH

  if error_file_path.exists():
    error_content = error_file_path.read_text()[-500:]

  payload = {
    "discord_user": report_data["DiscordUser"],
    "error_content": error_content,
    "frogpilot_toggles": frogpilot_toggles,
    "report": report_data["Issue"],
    "report_id": str(uuid.uuid4()),
    "report_schema_version": API_VERSION,
  }

  response = frogpilot_api.post("/v1/reports", json=payload, headers={"User-Agent": "frogpilot-api/1.0"}, timeout=30)

  if response is not None and 200 <= response.status_code < 300:
    if frogpilot_variables.params_memory.get("IssueReported", encoding="utf-8") == issue_reported:
      frogpilot_variables.params_memory.remove("IssueReported")

    print("Successfully sent error report!")
  else:
    status = "no_response" if response is None else response.status_code
    print(f"Error sending report (status={status})")

    time.sleep(60)
