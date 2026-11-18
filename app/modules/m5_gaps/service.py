def execute(text):
    from app.store import execute
    result=execute(text)
    return {"module":5, "report":result["reports"][4], "quarantine":result["quarantine"], "balance":result["balance"]}
