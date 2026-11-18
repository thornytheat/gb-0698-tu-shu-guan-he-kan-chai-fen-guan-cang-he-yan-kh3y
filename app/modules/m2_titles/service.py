def execute(text):
    from app.store import execute
    result=execute(text)
    return {"module":2, "report":result["reports"][1], "quarantine":result["quarantine"], "balance":result["balance"]}
