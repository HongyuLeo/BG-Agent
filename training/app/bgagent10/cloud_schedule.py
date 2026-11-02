"""Lazy complete-lobby batches. rounds=0 has no terminal round."""
def training_batches(config,completed):
    logical_round=0
    while config['rounds']==0 or logical_round<config['rounds']:
        remaining=config['games_per_round']
        while remaining:
            interval=config['eval_every_games']
            until_eval=interval-completed%interval if interval else remaining
            count=min(remaining,until_eval,config['workers'])
            remaining-=count;completed+=count
            final=bool(config['rounds'] and logical_round==config['rounds']-1 and remaining==0)
            yield logical_round,count,final
        logical_round+=1
