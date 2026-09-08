import sys, json; sys.path.insert(0,'ml')
import dataset, numpy as np
from final import prepare
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestClassifier
# Порядок важливий: y_drone_tracks_obl починається з y_drone_tracks, і при
# короткому збігу цілі над ОБЛАСТЮ підписувались як цілі на місто — на графіку
# виходили два однакові рядки з різними вагами.
NAMES = {"y_drone_tracks_obl":"цілі над Київщиною",
         "y_missile_tracks_obl":"ракетні цілі над Київщиною",
         "y_drone_tracks":"цілі курсом на Київ",
         "y_missile_tracks":"ракетні цілі на Київ",
         "y_alert_minutes":"хвилини тривог у місті",
         "y_attacked_i":"факт атаки на місто"}
SUF = {"_l1":"учора","_l2":"позавчора","_l3":"три доби тому","_m3":"середнє за 3 доби",
       "_m7":"середнє за 7 діб","_m14":"середнє за 14 діб","_m30":"середнє за 30 діб",
       "_sd7":"розкид за 7 діб","_max7":"максимум за 7 діб","_ewm":"згладжена історія"}
def human(c):
    for b, n in sorted(NAMES.items(), key=lambda kv: -len(kv[0])):
        if c.startswith(b):
            for sf, sn in SUF.items():
                if c.endswith(sf): return f"{n}: {sn}"
            return n
    return {"streak_prev":"довжина серії","days_since_strong":"діб від сильної доби",
            "night_hours":"тривалість ночі","month_sin":"сезон","month_cos":"сезон",
            "dow_sin":"день тижня","dow_cos":"день тижня"}.get(c, c)
d, feats = prepare(lag=1); d = dataset.add_labels(d)
m = Pipeline([("i", SimpleImputer(strategy="median")),
              ("m", RandomForestClassifier(n_estimators=500, min_samples_leaf=8,
                                           random_state=0, n_jobs=-1))])
m.fit(d[feats], d["y_attacked_i"])
imp = sorted(zip(feats, m[-1].feature_importances_), key=lambda x: -x[1])[:12]
json.dump([[human(c), round(float(v), 4)] for c, v in imp],
          open("site/api/importances.json", "w"), ensure_ascii=False, indent=1)
print("\n".join(f"{v:.4f}  {human(c)}" for c, v in imp))
