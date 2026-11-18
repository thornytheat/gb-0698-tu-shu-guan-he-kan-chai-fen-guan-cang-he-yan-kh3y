def execute(text):
    from app.store import execute
    result=execute(text)
    return {"module":1, "report":result["reports"][0], "quarantine":result["quarantine"], "balance":result["balance"]}
