from itertools import combinations
from tqdm import tqdm
from collections import defaultdict
import dynetx as dn
from .paths import *
import networkx as nx

__all__ = ["delta_conformity", "sliding_delta_conformity"]


def __label_frequency(g: dn.DynGraph, u: object, nodes: list, labels: list, hierarchies: dict = None) -> float:
    """
    Compute the similarity of node profiles
    :param g: a networkx Graph object
    :param u: node id
    :param labels: list of node categorical labels
    :param hierarchies: dict of labels hierarchies
    :return: node profiles similarity score in [-1, 1]
    """
    s = 1
    for label in labels:
        a_u = g._node[u][label]
        # set of nodes at given distance
        sgn = {}
        for v in nodes:
            # indicator function that exploits label hierarchical structure
            sgn[v] = 1 if a_u == g._node[v][label] else __distance(label, a_u, g._node[v][label], hierarchies)
            v_neigh = list(g.neighbors(v))
            # compute the frequency for the given node at distance n over neighbors label
            f_label = (len([x for x in v_neigh if g._node[x][label] == g._node[v][label]]) / len(v_neigh))
            f_label = f_label if f_label > 0 else 1
            sgn[v] *= f_label
        s *= sum(sgn.values()) / len(nodes)

    return s


def __distance(label: str, v1: str, v2: str, hierarchies: dict = None) -> float:
    """
    Compute the distance of two labels in a plain hierarchy
    :param label: label name
    :param v1: first label value
    :param v2: second label value
    :param hierarchies: labels hierarchies
    """
    if hierarchies is None or label not in hierarchies:
        return -1

    return -abs(hierarchies[label][v1] - hierarchies[label][v2]) / (len(hierarchies[label]) - 1)


def __normalize(u: object, scores: list, max_dist: int, alphas: list):
    """
    Normalize the computed scores in [-1, 1]
    :param u: node
    :param scores: datastructure containing the computed scores for u
    :param alphas: list of damping factor
    :return: scores updated
    """
    for alpha in alphas:
        norm = sum([(d ** -alpha) for d in range(1, max_dist + 1)])

        for profile in scores[str(alpha)]:
            scores[str(alpha)][profile][u] /= norm

    return scores


def delta_conformity(dg, start: int, delta: int, alphas: list, labels: list, profile_size: int = 1,
                     hierarchies: dict = None, path_type="shortest") -> dict:
    """
    Compute the Delta-Conformity for the considered dynamic graph
    :param dg: a dynetx Graph object composed by a single component
    :param start: the starting temporal id
    :param delta: the max duration of time respecting paths
    :param alphas: list of damping factors
    :param labels: list of node categorical labels
    :param profile_size:
    :param hierarchies: label hierarchies
    :param path_type: time respecting path type. String among: shortest, fastest, foremost, fastest_shortest and shortest_fastest (default: shortest)
    :return: conformity value for each node in [-1, 1]

    -- Example --
    >> g = dn.DynGraph()
    >>
    >>  labels = ['SI', 'NO']
    >>  nodes = ['A', 'B', 'C', 'D']
    >>
    >> for node in nodes:
    >>      g.add_node(node, labels=random.choice(labels))
    >>
    >>  g.add_interaction("A", "B", 1, 4)
    >>  g.add_interaction("B", "D", 2, 5)
    >>  g.add_interaction("A", "C", 4, 8)
    >>  g.add_interaction("B", "D", 2, 4)
    >>  g.add_interaction("B", "C", 6, 10)
    >>  g.add_interaction("B", "D", 2, 4)
    >>  g.add_interaction("A", "B", 7, 9)
    >>
    >>  res = al.delta_conformity(g, 1, 5, list(np.arange(1, 4, 0.2)), ['labels'], profile_size=1, path_type="fastest")

    """

    if profile_size > len(labels):
        raise ValueError("profile_size must be <= len(labels)")

    if len(alphas) < 1 or len(labels) < 1:
        raise ValueError("At list one value must be specified for both alphas and labels")

    profiles = []
    for i in range(1, profile_size + 1):
        profiles.extend(combinations(labels, i))

    g = dg.time_slice(t_from=start, t_to=start + delta)

    # Attribute value frequency
    labels_value_frequency = defaultdict(lambda: defaultdict(int))

    for _, metadata in g.nodes(data=True):
        for k, v in metadata.items():
            labels_value_frequency[k][v] += 1

    # Normalization
    df = defaultdict(lambda: defaultdict(int))
    for k, v in labels_value_frequency.items():
        tot = 0
        for p, c in v.items():
            tot += c

        for p, c in v.items():
            df[k][p] = c / tot

    res = {str(a): {"_".join(profile): {n: 0 for n in g.nodes()} for profile in profiles} for a in alphas}

    sp = all_time_respecting_paths(g, start, delta + start)

    distances = defaultdict(lambda: defaultdict(int))
    for k, v in sp.items():
        distances[k[0]][k[1]] = len(annotate_paths(v)[path_type])

    for u in tqdm(g.nodes()):

        sp = dict(distances[u])

        dist_to_nodes = defaultdict(list)
        for node, dist in sp.items():
            dist_to_nodes[dist].append(node)
        sp = dist_to_nodes

        for dist, nodes in sp.items():
            if dist != 0:
                for profile in profiles:
                    sim = __label_frequency(g, u, nodes, list(profile), hierarchies)

                    for alpha in alphas:
                        partial = sim / (dist ** alpha)
                        p_name = "_".join(profile)
                        res[str(alpha)][p_name][u] += partial

        if len(sp) > 0:
            res = __normalize(u, res, max(sp.keys()), alphas)

    return res


def sliding_delta_conformity(dg, delta: int, alphas: list, labels: list, profile_size: int = 1,
                             hierarchies: dict = None, path_type="shortest") -> dict:
    """
    Compute the Delta-Conformity for the considered dynamic graph on a sliding window of predefined size

    :param dg: a dynetx Graph object composed by a single component
    :param delta: the max duration of time respecting paths
    :param alphas: list of damping factors
    :param labels: list of node categorical labels
    :param profile_size:
    :param hierarchies: label hierarchies
    :param path_type: time respecting path type. String among: shortest, fastest, foremost, fastest_shortest and shortest_fastest (default: shortest)
    :return: conformity trend value for each node

    -- Example --

    >> g = dn.DynGraph()
    >>
    >>  labels = ['SI', 'NO']
    >>  nodes = ['A', 'B', 'C', 'D']
    >>
    >> for node in nodes:
    >>      g.add_node(node, labels=random.choice(labels))
    >>
    >>  g.add_interaction("A", "B", 1, 4)
    >>  g.add_interaction("B", "D", 2, 5)
    >>  g.add_interaction("A", "C", 4, 8)
    >>  g.add_interaction("B", "D", 2, 4)
    >>  g.add_interaction("B", "C", 6, 10)
    >>  g.add_interaction("B", "D", 2, 4)
    >>  g.add_interaction("A", "B", 7, 9)
    >>
    >>  res = al.sliding_delta_conformity(g, 2, list(np.arange(1, 4, 0.2)), ['labels'], profile_size=1, path_type="fastest")

    """
    tids = dn.temporal_snapshots_ids(dg)

    alpha_attribute_node_to_seq = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for t in tids:
        if t + delta < tids[-1]:
            dconf = delta_conformity(dg, t, delta, alphas, labels, profile_size, hierarchies, path_type)
            for alpha, data in dconf.items():
                for attribute, node_values in data.items():
                    for n, v in node_values.items():
                        alpha_attribute_node_to_seq[alpha][attribute][n].append((t + delta, v))

    return alpha_attribute_node_to_seq
