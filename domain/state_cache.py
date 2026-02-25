from config import STATE, STATUS_TODO

def get_todo_count_cached() -> int:
    """
    Returns the cached number of TODO items. 
    Does NOT hit the API to keep UI fast. 
    The cache is updated by background jobs or user actions.
    """
    return STATE.get("todo_count", 0)

def update_todo_count(count: int):
    STATE["todo_count"] = count
