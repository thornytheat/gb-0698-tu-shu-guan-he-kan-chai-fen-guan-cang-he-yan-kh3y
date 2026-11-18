def execute(text):
    from app.store import execute
    result=execute(text)
    return {"module":4, "report":result["reports"][3], "quarantine":result["quarantine"], "balance":result["balance"]}
