# admin_tools.py

PNCO_RANKS = [
    "Patrolman/Patrolwoman",
    "Police Corporal",
    "Police Staff Sergeant",
    "Police Master Sergeant",
    "Police Senior Master Sergeant",
    "Police Chief Master Sergeant",
    "Police Executive Master Sergeant"
]

PCO_RANKS = [
    "Police Lieutenant",
    "Police Captain",
    "Police Major",
    "Police Lieutenant Colonel",
    "Police Colonel",
    "Police Brigadier General",
    "Police Major General",
    "Police Lieutenant General",
    "Police General"
]

player_ranks = {}

def get_rank_for_user(username):
    return player_ranks.get(username, "No Rank Assigned")

def set_rank_for_user(username, rank):
    if rank not in PNCO_RANKS and rank not in PCO_RANKS:
        raise ValueError("Invalid rank")
    player_ranks[username] = rank

def promote_user(username):
    current_rank = player_ranks.get(username)
    if not current_rank:
        return "User has no rank assigned."
    if current_rank in PNCO_RANKS:
        idx = PNCO_RANKS.index(current_rank)
        if idx < len(PNCO_RANKS) - 1:
            player_ranks[username] = PNCO_RANKS[idx + 1]
            return f"User promoted to {player_ranks[username]}"
    elif current_rank in PCO_RANKS:
        idx = PCO_RANKS.index(current_rank)
        if idx < len(PCO_RANKS) - 1:
            player_ranks[username] = PCO_RANKS[idx + 1]
            return f"User promoted to {player_ranks[username]}"
    return "Already at highest rank."

def demote_user(username):
    current_rank = player_ranks.get(username)
    if not current_rank:
        return "User has no rank assigned."
    if current_rank in PNCO_RANKS:
        idx = PNCO_RANKS.index(current_rank)
        if idx > 0:
            player_ranks[username] = PNCO_RANKS[idx - 1]
            return f"User demoted to {player_ranks[username]}"
    elif current_rank in PCO_RANKS:
        idx = PCO_RANKS.index(current_rank)
        if idx > 0:
            player_ranks[username] = PCO_RANKS[idx - 1]
            return f"User demoted to {player_ranks[username]}"
    return "Already at lowest rank."

def delete_user(username):
    if username in player_ranks:
        del player_ranks[username]
        return f"{username} deleted."
    return "User not found."

def add_user(username, rank):
    set_rank_for_user(username, rank)
    return f"{username} added with rank {rank}."
