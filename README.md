# GTA VI Trophy Rarity Forecaster

A refresh/dilution-aware forecaster for Grand Theft Auto VI PlayStation 5 trophy earn rates on Exophase. For each of the game's 55 trophies it forecasts five quantiles (5/25/50/75/95%) of the earn rate at the target time, from the history of Exophase reads in the case file.

The program is Python 3.13, standard library only, deterministic, and runs in under a second per case. It recovers integer earners from each read's rates, measures refresh behaviour from the history (tracked-base growth, earners growth, new-cohort earn odds), and projects players and earners to the target as a mixture over a lognormal refresh gap — median on the refreshed value, upper tail carrying the no-refresh chance.

Local practice score (pinball loss, logit scale): **0.077** mean over the two practice cases, vs the house persistence baseline at ~1.51.

[![make.fun](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Calistaa113/gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Calistaa113/gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
