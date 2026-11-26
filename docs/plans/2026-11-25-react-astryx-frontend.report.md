# superlite build report

projection: fixed forecast saved at lint 2026-11-25T15:52:17 (plan edited since)

                         Projected    Actual  Delta
wall-clock (min)              10.5     174.8  +164.3 (+1570%)
agent cost (USD, +rework)      1.74      5.77  +4.03 (+232%)
task-minutes                  65.7     234.4  +168.8 (+257%)
agents                          20        23  +3 (+15%)
cost split: agents $5.18, rework $0.59, coordinator $12.99, total $18.76
concurrency: peak 8 at once (projected 10); critical path actual T0; projected T1 > T20 (7.6 min)
model mix: haiku 3 tasks $0.65, sonnet 11 tasks $5.12, coordinator opus $12.99
quality: tests 1234 passed, 0 failed; first-time pass n/a; rework dispatches 2; open incidents 46

task  model      pred  actual  delta             cost
T4    sonnet      4.0    30.7  +26.7 (+673%)   $0.681
T1    sonnet      4.1    30.2  +26.1 (+640%)   $0.509
T6    sonnet      3.6    27.5  +23.9 (+662%)   $0.462
T8    sonnet      3.6    27.4  +23.8 (+660%)   $0.279
T7    sonnet      4.3    25.0  +20.7 (+479%)   $0.534
(+9 smaller misses; `superlite-cli report --json` lists all)

agent cost table:
| agent | model | wall_min | tokens | usd |
| --- | --- | --- | --- | --- |
| a0eb4668eb0889715 | sonnet | 2.1703 | 184910 | 0.1154 |
| a102284aa452e65da | sonnet | 45.5319 | 3725351 | 1.0982 |
| a117d76e3527c3f50 | sonnet | 106.3986 | 955474 | 0.4851 |
| a1382ffc38ee06fa9 | haiku | 32.8813 | 802696 | 0.0266 |
| a2c5e470babce569f | sonnet | 36.4294 | 1803927 | 0.6038 |
| a2e671c8496dec350 | sonnet | 29927186.8849 | 0 | 0.0 |
| a34c1b840337bbee1 | sonnet | 29927460.4641 | 0 | 0.0 |
| a34da18cb53c8c341 | sonnet | 29927196.9335 | 0 | 0.0 |
| a47115f74ea1c1103 | sonnet | 34.9757 | 1850556 | 0.9303 |
| a5a59a6b712db51c7 | sonnet | 29927195.5938 | 0 | 0.0 |
| a5ae5a630ac298d34 | opus | 0.6339 | 33279 | 0.1981 |
| a60962cccb844f09b | sonnet | 29927448.4939 | 0 | 0.0 |
| a6e84de4333e46130 | sonnet | 29927201.7976 | 0 | 0.0 |
| a6ff42ce9712bf816 | sonnet | 29927364.637 | 1993247 | 0.6815 |
| aa664c46efada9eda | sonnet | 29927443.0792 | 0 | 0.0 |
| aab864da3fe3031c9 | sonnet | 44.0776 | 1566489 | 0.6749 |
| aba25f8fbbc986cd9 | haiku | 20.4349 | 1239410 | 0.0327 |
| ac86dbcdbe12fda41 | sonnet | 29927364.5403 | 0 | 0.0 |
| ace43bb25dab2079c | sonnet | 29927371.6 | 2587667 | 1.0138 |
| ade868d1c20f3f0d6 | sonnet | 5.7189 | 173977 | 0.1057 |
| aeb039111eecdcbce | sonnet | 29927192.8366 | 0 | 0.0 |
| aeead6b2bfc0fff4d | sonnet | 29927329.8238 | 0 | 0.0 |
| afcbdef535a7c677c | sonnet | 29927431.5251 | 0 | 0.0 |
| totals |  | 389055517.4623 | 16916983 | 5.9661 |
cost source: est

trend (last 1 run): first-time pass n/a; findings 5; rework+fixer cost 10%
lessons: 2 cached, 0 proven
takeaway: ran 1570% slower than projected; cost 232% over; biggest miss T4
