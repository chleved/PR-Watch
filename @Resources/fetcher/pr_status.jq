def failing: [.statusCheckRollup[]? | select(
  ((.conclusion // "") | IN("FAILURE","TIMED_OUT","STARTUP_FAILURE","ACTION_REQUIRED")) or
  ((.state // "") | IN("FAILURE","ERROR")))] | length;
def running: [.statusCheckRollup[]? | select(
  ((.status // "COMPLETED") != "COMPLETED") or
  ((.state // "") | IN("PENDING","EXPECTED")))] | length;
def opinions: [.reviews[]?
    | select(.state | IN("APPROVED","CHANGES_REQUESTED","DISMISSED"))
    | select(.authorAssociation | IN("OWNER","MEMBER","COLLABORATOR"))]
  | group_by(.author.login)
  | map(sort_by(.submittedAt) | last)
  | map(select(.state != "DISMISSED"));
def decision:
  if (.reviewDecision // "") != "" then .reviewDecision
  else opinions as $o
    | if any($o[]; .state=="CHANGES_REQUESTED") then "CHANGES_REQUESTED"
      elif any($o[]; .state=="APPROVED") then "APPROVED"
      else "" end
  end;
{
  status: (
    if   .state=="MERGED"               then "MERGED"
    elif .state=="CLOSED"               then "CLOSED"
    elif .isDraft                       then "DRAFT"
    elif .mergeable=="CONFLICTING"      then "CONFLICT"
    elif failing > 0                    then "CI-FAIL"
    elif decision=="CHANGES_REQUESTED"  then "CHANGES"
    elif running > 0                    then "CI-RUNNING"
    elif decision=="APPROVED"           then "APPROVED"
    else "WAITING" end
  ),
  title: .title,
  createdAt: .createdAt,
  url: .url,
  headRefOid: .headRefOid,
  baseRefName: .baseRefName,
  msg_dates: (
    [ .comments[]?.createdAt ] +
    [ .reviews[]? | select((.body // "") != "" or (.state != "COMMENTED")) | .submittedAt ]
  )
}
