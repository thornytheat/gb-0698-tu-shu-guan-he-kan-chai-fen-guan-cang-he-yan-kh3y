def execute(text):
    from app.store import execute
    result=execute(text)
    return {"module":7, "report":result["reports"][6], "quarantine":result["quarantine"], "balance":result["balance"]}
