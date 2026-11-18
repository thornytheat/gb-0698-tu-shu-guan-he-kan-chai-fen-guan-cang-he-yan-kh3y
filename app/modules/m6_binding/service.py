def execute(text):
    from app.store import execute
    result=execute(text)
    return {"module":6, "report":result["reports"][5], "quarantine":result["quarantine"], "balance":result["balance"]}
