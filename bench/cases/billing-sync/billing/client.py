class StripeLikeClient:
    def __init__(self):
        self.plans = {}

    def upsert_plan(self, plan_id, amount, interval):
        self.plans[plan_id] = {"amount": amount, "interval": interval}
