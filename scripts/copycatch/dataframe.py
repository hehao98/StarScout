import logging
import pandas as pd

from collections import defaultdict

from .iterative import CopyCatchParams


logger = logging.getLogger(__name__)


USER_KEY, REPO_KEY, TIME_KEY = None, None, None
COPYCATCH_PARAMS: CopyCatchParams = None
MATRIX: dict[tuple[str, str], float] = dict()
MIN_REPO_STARS: int = None
NUM_SAMPLES_PER_REPO: int = None


def run(
    df: pd.DataFrame,
    copycatch_params: CopyCatchParams,
    max_iter: int = 100,
    min_repo_stars: int = 50,
    num_samples_per_repo: int = 10,
    user_key: str = "actor",
    repo_key: str = "repo_name",
    time_key: str = "starred_at",
) -> pd.DataFrame:
    global COPYCATCH_PARAMS, MIN_REPO_STARS, NUM_SAMPLES_PER_REPO
    global USER_KEY, REPO_KEY, TIME_KEY

    COPYCATCH_PARAMS = copycatch_params
    MIN_REPO_STARS = min_repo_stars
    NUM_SAMPLES_PER_REPO = num_samples_per_repo

    if user_key not in df.columns or repo_key not in df.columns:
        raise ValueError("Invalid column names")
    if time_key not in df.columns:
        raise ValueError("Invalid column names")
    if df[time_key].dtype != "float64":  # convert to unix timestamp
        df[time_key] = pd.to_datetime(df[time_key]).astype(int) / 1e9
    USER_KEY, REPO_KEY, TIME_KEY = user_key, repo_key, time_key
    for user, repo, time in df[[USER_KEY, REPO_KEY, TIME_KEY]].itertuples(index=False):
        MATRIX[(user, repo)] = time

    centers = _get_initial_centers(df)
    logger.debug("\n%s", centers)

    for i in range(max_iter):
        users = _map_users(df, centers)
        logger.debug("Iteration %d users\n%s", i, users)
        centers = _reduce_centers(df, users, centers)
        logger.debug("Iteration %d centers\n%s", i, centers)

    users = _map_users(df, centers)
    return (
        users.groupby("cluster_id")
        .agg(users=("user", list))
        .join(centers.set_index("cluster_id"))
        .reset_index()
    )


def _get_initial_centers(df: pd.DataFrame) -> pd.DataFrame:
    repo_to_actors = df.groupby(by=REPO_KEY).agg(
        n_actors=(USER_KEY, "nunique"),
        repo_center=(TIME_KEY, "mean"),
        actors=(USER_KEY, "unique"),
    )
    repo_to_actors = repo_to_actors[repo_to_actors.n_actors >= MIN_REPO_STARS]
    logger.debug("%d repos >= %d stars", len(repo_to_actors), MIN_REPO_STARS)

    """
    repo_to_actors["cluster"] = repo_to_actors.actors.map(
        lambda x: df[df[USER_KEY].isin(set(x))][REPO_KEY]
        .value_counts()
        .index[: (COPYCATCH_PARAMS.m - 1) * NUM_SAMPLES_PER_REPO + 1]
        .tolist()
    )

    repo_to_actors["cluster"] = repo_to_actors["cluster"].map(
        lambda x: (
            [[x[0]] + list(y) for y in batched(x[1:], COPYCATCH_PARAMS.m - 1)]
            if len(x) > 1
            else [x]
        )
    )
    initial_centers = repo_to_actors.explode("cluster").reset_index()
    initial_centers["center"] = initial_centers["cluster"].map(
        lambda c: repo_to_actors.loc[c].center.to_dict()
    )
    """

    centers = repo_to_actors.reset_index()[["repo_name", "repo_center"]]
    centers["centers"] = centers.apply(lambda x: {x.repo_name: x.repo_center}, axis=1)
    centers["clusters"] = centers.repo_name.map(lambda x: [x])
    centers.insert(0, "cluster_id", range(len(centers)))
    return centers


def _map_users(df: pd.DataFrame, centers: pd.DataFrame) -> pd.DataFrame:
    results = []
    for user in set(df[USER_KEY]):
        for k, center, clusters in zip(
            centers["cluster_id"], centers["centers"], centers["clusters"]
        ):
            theta = 0
            for repo in clusters:
                if (user, repo) in MATRIX and abs(
                    MATRIX[(user, repo)] - center[repo]
                ) <= COPYCATCH_PARAMS.delta_t:
                    theta += 1
            if theta >= COPYCATCH_PARAMS.rho * len(clusters):
                results.append({"cluster_id": k, "user": user})
    return pd.DataFrame(results)


def _reduce_centers(
    df: pd.DataFrame, users: pd.DataFrame, centers: pd.DataFrame
) -> pd.DataFrame:
    repos = set(df[REPO_KEY])
    users = (
        users.groupby(by="cluster_id")
        .agg(users=("user", list))
        .join(centers.set_index("cluster_id"))
    )
    results = []

    for cluster_id, repo_name, repo_center, users, centers in zip(
        users.index, users.repo_name, users.repo_center, users.users, users.centers
    ):
        new_center = defaultdict(lambda: {"c": 0, "p": 0, "v": 0})

        for user in users:
            for repo in repos:
                c = centers[repo] if repo in centers else repo_center
                if (user, repo) in MATRIX and (
                    abs(MATRIX[(user, repo)] - c) <= COPYCATCH_PARAMS.delta_t
                ):
                    new_center[repo]["c"] += MATRIX[(user, repo)]
                    new_center[repo]["p"] += 1
                    new_center[repo]["v"] += (c - MATRIX[(user, repo)]) ** 2

        for repo in new_center:
            new_center[repo]["v"] = new_center[repo]["v"] / new_center[repo]["p"]
            new_center[repo]["c"] = new_center[repo]["c"] / new_center[repo]["p"]

        new_center = sorted(new_center.items(), key=lambda x: (-x[1]["p"], x[1]["v"]))

        results.append(
            {
                "cluster_id": cluster_id,
                "repo_name": repo_name,
                "repo_center": repo_center,
                "centers": {k: v["c"] for k, v in new_center},
                "clusters": [k for k, _ in new_center[: COPYCATCH_PARAMS.m]],
            }
        )

    return pd.DataFrame(results)
