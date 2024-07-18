import logging
import numpy as np
import pandas as pd
import multiprocessing as mp

from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)


@dataclass
class CopyCatchParams:
    delta_t: float  # time window size in seconds
    n: int  # min. number of users in the cluster
    m: int  # min. number of repos in the cluster
    rho: float  # relaxation term for cluster density
    beta: float  # relaxation term for time window


class AdjacencyMatrix:
    def __init__(self, N: int, M: int):
        self.N = N
        self.M = M
        self.data: dict[dict, float] = dict()

    def non_zero_row(self, i) -> dict[int, float]:
        return self.data.get(i, {})

    def non_zero_col(self, j) -> dict[int, float]:
        return {i: self.data[i].get(j) for i in range(self.N) if j in self.data[i]}

    def __getitem__(self, key: tuple[int, int]) -> float:
        if key[0] in self.data:
            return self.data[key[0]].get(key[1], 0.0)
        return 0.0

    def __setitem__(self, key: tuple[int, int], value: float):
        if key[0] not in self.data:
            self.data[key[0]] = dict()
        self.data[key[0]][key[1]] = value


class CopyCatch:

    @staticmethod
    def from_df(
        params: CopyCatchParams,
        df: pd.DataFrame,
        user_key: str = "actor",
        repo_key: str = "repo_name",
        time_key: str = "starred_at",
    ) -> "CopyCatch":
        if user_key not in df.columns or repo_key not in df.columns:
            raise ValueError("Invalid column names")
        if time_key not in df.columns:
            raise ValueError("Invalid column names")
        if df[time_key].dtype != "float64":  # convert to unix timestamp
            df[time_key] = pd.to_datetime(df[time_key]).astype(int) / 1e9

        return CopyCatch(
            users=df[user_key].tolist(),
            repos=df[repo_key].tolist(),
            stars=set(zip(df[user_key], df[repo_key], df[time_key])),
            params=params,
        )

    def __init__(
        self,
        users: list[str],
        repos: list[str],
        stars: set[tuple[str, str, float]],
        params: CopyCatchParams,
    ):
        self.users = sorted(set(users))
        self.repos = sorted(set(repos))
        self.user2id = {user: i for i, user in enumerate(self.users)}
        self.repo2id = {repo: i for i, repo in enumerate(self.repos)}

        self.N = len(self.users)
        self.M = len(self.repos)
        self.U = AdjacencyMatrix(self.N, self.M)
        for user, repo, time in stars:
            assert time > 0
            self.U[self.user2id[user], self.repo2id[repo]] = time

        self.delta_t = params.delta_t
        self.n = params.n
        self.m = params.m
        self.rho = params.rho
        self.beta = params.beta

    def run_all(
        self, n_jobs: int = 1, max_iter: int = 100
    ) -> list[tuple[set[str], set[str]]]:
        results = []
        if n_jobs == 1:
            for i in range(self.M):
                seed_repo_ids = self.find_closest_repos(i, self.m)
                users, repos = self.run_once(seed_repo_ids, max_iter)
                if len(users) >= self.n:
                    results.append((users, repos))
        else:
            params = set(
                (self.find_closest_repos(i, self.m), max_iter) for i in range(self.M)
            )
            with mp.Pool(n_jobs) as pool:
                for users, repos in pool.starmap(self.run_once, params):
                    if len(users) >= self.n:
                        results.append((users, repos))
        return results

    def run_once(
        self, repo_ids: set[int], max_iter: int = 100
    ) -> tuple[set[str], set[str]]:
        assert len(repo_ids) == self.m

        seed_center = np.zeros(self.M)
        for i in repo_ids:
            seed_center[i] = np.mean(list(self.U.non_zero_col(i).values()))
        logger.info("Seed: %s", repo_ids)

        center, rids = self._s_copy_catch(seed_center, repo_ids, max_iter)
        uids, _ = self._find_users(center, rids)

        users = {self.users[uid] for uid in uids}
        repos = {self.repos[rid] for rid in rids}
        logger.info("%s <- %s", repos, users)
        return users, repos

    def find_closest_repos(self, repo_id: int, k: int) -> set[int]:
        assert 0 <= repo_id < self.M and k > 0

        repo_id_to_dist = dict()
        user_ids = set(self.U.non_zero_col(repo_id).keys())
        for j in range(self.M):
            repo_id_to_dist[j] = len(user_ids & set(self.U.non_zero_col(j).keys()))
        sorted_rids = sorted(list(repo_id_to_dist.items()), key=lambda x: -x[1])
        sorted_rids = [rid for rid, _ in sorted_rids]
        return set(sorted_rids[:k])

    def _s_copy_catch(
        self, seed_center: np.ndarray, seed_repo_ids: set[int], max_iter: int
    ) -> tuple[np.ndarray, set[int]]:
        assert seed_center.shape == (self.M,)

        center, repo_ids = seed_center.copy(), seed_repo_ids.copy()
        for _ in range(max_iter):
            logger.debug("Curr center ndarray(%s), repo ids %s", center.shape, repo_ids)
            center_old, repo_ids_old = center.copy(), repo_ids.copy()
            center = self._update_center(center, repo_ids)
            repo_ids = self._update_subspace(center, repo_ids)
            if np.allclose(center_old, center) and repo_ids_old == repo_ids:
                break

        return center, repo_ids

    def _update_center(self, center: np.ndarray, repo_ids: set[int]) -> np.ndarray:
        assert center.shape == (self.M,)
        logger.debug("Updating ndarray(%s) with repo ids %s", center.shape, repo_ids)

        curr_uids, _ = self._find_users(center, repo_ids)
        if len(curr_uids) == 0:
            logger.debug("No users found for center %s", center)
            return center

        c_new = np.zeros(self.M)
        for rid in repo_ids:
            c_new[rid] = np.mean(list(self.U.non_zero_col(rid).values()))
        logger.debug("Caliberated center ndarray(%s)", c_new.shape)
        for rid in repo_ids:
            curr_uids, w = self._find_users(
                c_new, repo_ids, rid, self.beta * self.delta_t
            )
            _, c_new[rid] = self._find_center(curr_uids, w, rid)

        return c_new

    def _update_subspace(self, center: np.ndarray, repo_ids: set[int]) -> set[int]:
        assert center.shape == (self.M,)
        logger.debug("Updating subspace %s, center=ndarray%s", repo_ids, center.shape)

        all_rids, next_rids = set(range(self.M)), repo_ids.copy()
        uids, _ = self._find_users(center, repo_ids)
        for rid in repo_ids:
            curr_uids, _ = self._find_users(center, {rid}, user_ids_all=uids)
            curr_rid = rid
            for rid2 in all_rids - repo_ids:
                next_uids, _ = self._find_users(center, {rid2}, user_ids_all=uids)
                if curr_uids < next_uids:
                    curr_uids = next_uids
                    curr_rid = rid2
            next_rids = (next_rids - {rid}) | {curr_rid}

        logger.debug("Updated subspace %s", next_rids)
        return next_rids

    def _find_center(
        self, user_ids: set[int], user_weights: np.ndarray, center_repo_id: int
    ) -> tuple[set[int], float]:
        assert user_weights.shape == (self.N,)
        logger.debug(
            "_find_center(user_ids=%s, user_weights=%s, center_repo_id=%s",
            user_ids,
            user_weights,
            center_repo_id,
        )

        if len(user_ids) == 0:
            return set(), 0.0

        sorted_uids = sorted(user_ids, key=lambda i: self.U[i, center_repo_id])

        # Scan using sliding window from i to j
        i, j, curr_delta, weight_sum = 0, 0, 0, user_weights[sorted_uids[0]]
        max_i, max_j, max_weight_sum = 0, 0, user_weights[sorted_uids[0]]
        while i < self.N and j < self.N:
            if curr_delta <= 2 * self.delta_t:
                if weight_sum >= max_weight_sum:
                    max_i, max_j, max_weight_sum = i, j, weight_sum
                j += 1
                if j < len(sorted_uids):
                    weight_sum += user_weights[sorted_uids[j]]
                    curr_delta = (
                        self.U[sorted_uids[j], center_repo_id]
                        - self.U[sorted_uids[i], center_repo_id]
                    )
            else:
                i += 1
                if i < len(sorted_uids):
                    weight_sum -= user_weights[sorted_uids[i - 1]]
                    curr_delta = (
                        self.U[sorted_uids[j], center_repo_id]
                        - self.U[sorted_uids[i], center_repo_id]
                    )

        sub_uids = set(sorted_uids[max_i : max_j + 1])
        sub_center = np.mean([self.U[uid, center_repo_id] for uid in sub_uids])
        logger.debug("Found uids %s with center %s", sub_uids, sub_center)
        return sub_uids, sub_center

    def _find_users(
        self,
        center: np.ndarray,
        repo_ids: set[int],
        center_repo_id: int = -1,
        relaxed_delta_t: float = 0,
        user_ids_all: Optional[set[int]] = None,
    ) -> tuple[set[int], np.ndarray]:
        assert center.shape == (self.M,)
        logger.debug(
            "_find_users(center=%s, repo_ids=%s, center_repo_id=%s, "
            "relaxed_delta_t=%s, user_ids_all=%s)",
            center.shape,
            repo_ids,
            center_repo_id,
            relaxed_delta_t,
            user_ids_all,
        )

        if user_ids_all is None:
            user_ids_all = range(self.N)

        user_ids, user_weights = set(), np.zeros(self.N)
        for uid in user_ids_all:
            for rid in repo_ids:
                if self.U[uid, rid] > 0 and (
                    abs(center[rid] - self.U[uid, rid]) < self.delta_t
                    or (
                        rid == center_repo_id
                        and abs(center[rid] - self.U[uid, rid]) < relaxed_delta_t
                    )
                ):
                    user_weights[uid] += 1
            if user_weights[uid] >= self.rho * self.m or np.isclose(
                user_weights[uid], self.rho * self.m
            ):
                user_ids.add(uid)

        logger.debug("Found users %s with weights %s", user_ids, user_weights)
        return user_ids, user_weights
