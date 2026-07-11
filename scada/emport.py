#!/usr/bin/env python3
"""Headless SCADA-LTS Emport (export / import) for versioning the config.

SCADA-LTS's Import/Export is a DWR-backed UI feature (EmportDwr). This drives it
over HTTP so the data-source + data-point config can be exported to JSON, committed,
and re-imported without clicking through the UI.

  python3 emport.py export scada/emport-config.json     # serialize DS + points -> JSON
  python3 emport.py import scada/emport-config.json      # (re)create from JSON

Env: SCADA_URL (default http://192.168.1.94:8080/Scada-LTS), SCADA_USER/SCADA_PASS
(default admin/admin — the exercise's intentional planted default cred).

Notes:
- Import is additive/upsert by xid: points are matched on xid and created/updated;
  it does NOT delete points absent from the JSON, so it is safe against the live rig.
- Only dataSources + dataPoints are exported here (no views/users/values). Graphical
  views are still placed in the UI (see README).
"""
import json, os, re, sys, urllib.request, urllib.parse, http.cookiejar

BASE = os.environ.get("SCADA_URL", "http://192.168.1.94:8080/Scada-LTS")
USER = os.environ.get("SCADA_USER", "admin")
PASS = os.environ.get("SCADA_PASS", "admin")

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))

def _post(path, data):
    req = urllib.request.Request(BASE + path, data=data.encode(), method="POST")
    req.add_header("Content-Type", "text/plain")
    return _opener.open(req, timeout=25).read().decode("utf-8", "replace")

def auth():
    _post("/api/auth/%s/%s" % (USER, PASS), "")

def script_session():
    body = ("callCount=1\nc0-scriptName=__System\nc0-methodName=generateId\nc0-id=0\n"
            "batchId=0\ninstanceId=0\npage=%2FScada-LTS%2Femport.shtm\nscriptSessionId=\n")
    r = _post("/dwr/call/plaincall/__System.generateId.dwr", body)
    m = re.search(r'_remoteHandleCallback\([\'"]\d+[\'"],[\'"]\d+[\'"],"([^"]+)"', r)
    return m.group(1) if m else "0000000000000000"   # __System is often locked; a dummy id is accepted

# createExportData(...) descriptor is (IZ...ZIZZZ): params 0 and 16 are int, the rest boolean.
_EXPORT_ORDER = ["prettyIndent","graphicalViews","eventHandlers","dataSources","dataPoints",
    "scheduledEvents","compoundEventDetectors","pointLinks","users","pointHierarchy",
    "mailingLists","publishers","watchLists","maintenanceEvents","scripts","pointValues",
    "pointValuesMax","systemSettings","usersProfiles","reports"]
_EXPORT_DESCR = "IZZZZZZZZZZZZZZZIZZZ"

def export(path, want=("dataSources", "dataPoints")):
    ssid = script_session()
    lines = ["callCount=1","c0-scriptName=EmportDwr","c0-methodName=createExportData","c0-id=0"]
    for i, k in enumerate(_EXPORT_ORDER):
        if _EXPORT_DESCR[i] == "I":
            lines.append("c0-param%d=int:%d" % (i, 3 if k == "prettyIndent" else 0))
        else:
            lines.append("c0-param%d=boolean:%s" % (i, "true" if k in want else "false"))
    lines += ["batchId=1","instanceId=0","page=%2FScada-LTS%2Femport.shtm","scriptSessionId=" + ssid, ""]
    r = _post("/dwr/call/plaincall/EmportDwr.createExportData.dwr", "\n".join(lines))
    m = re.search(r'_remoteHandleCallback\([\'"]\d+[\'"],[\'"]\d+[\'"],(.*)\);', r, re.S)
    if not m or not m.group(1).strip().startswith('"'):
        sys.exit("export failed:\n" + r[:1500])
    open(path, "w").write(json.loads(m.group(1).strip()))
    print("wrote", path)

def do_import(path):
    txt = open(path).read()
    ssid = script_session()
    payload = ("callCount=1\nc0-scriptName=EmportDwr\nc0-methodName=importData\nc0-id=0\n"
               "c0-param0=string:" + urllib.parse.quote(txt, safe="") + "\n"
               "batchId=2\ninstanceId=0\npage=%2FScada-LTS%2Femport.shtm\nscriptSessionId=" + ssid + "\n")
    print(_post("/dwr/call/plaincall/EmportDwr.importData.dwr", payload)[:800])

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "import"):
        sys.exit(__doc__)
    auth()
    (export if sys.argv[1] == "export" else do_import)(sys.argv[2])
