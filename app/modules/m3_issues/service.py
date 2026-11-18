def execute(text):
    from app.store import execute
    result=execute(text)
    return {"module":3, "report":result["reports"][2], "quarantine":result["quarantine"], "balance":result["balance"]}
