from scipy.spatial import distance
import numpy as np
from sklearn.cluster import KMeans, AgglomerativeClustering, SpectralClustering
from sklearn_extra.cluster import KMedoids
from sklearn.metrics import silhouette_score
from sklearn.decomposition import PCA
import pandas as pd
import matplotlib.pyplot as plt
from tqdm.auto import tqdm
import warnings
from tabulate import tabulate
from nltk.probability import FreqDist
from typing import Union
import random
import math


# Exceptions ####################################################
# Silhouette Error won't work on a WUM with length 1
class SilhouetteError(Exception):
    pass


class pcaError(Exception):
    pass


##################################################################
def part(dataframe):
    grouped = dataframe.groupby(dataframe.cluster)
    return [(i, grouped.get_group(i)) for i in set(dataframe['cluster'].to_list())]


# TODO: documentation
def match(score1, score2):
    cos = distance.cosine

    def prototype(dataframe):
        x = dataframe['x'].to_list()
        y = dataframe['y'].to_list()
        vecs = [np.array([x[i], y[i]]) for i in range(len(x))]
        return np.array(sum(vecs)) / len(vecs)

    df1 = score1.df.copy(deep=True)
    df2 = score2.df.copy(deep=True)

    clusters = lambda i: [x[0] for x in i]

    # make partitioned clusters with prototypes
    df1_partitioned = [(clus, prototype(df)) for clus, df in part(df1)]
    df2_partitioned = [(clus, prototype(df)) for clus, df in part(df2)]

    df1_clusters = clusters(df1_partitioned)
    df2_clusters = clusters(df2_partitioned)

    scores = []
    # make list of scores
    for clus1, proto1 in df1_partitioned:
        for clus2, proto2 in df2_partitioned:
            score_data = {'clus1': clus1, 'clus2': clus2, 'dist': cos(proto1, proto2)}
            scores.append(score_data)

    # sort list of scores by distance, in ascending order
    scores.sort(key=lambda i: i['dist'])

    change_rules = {}

    # if there are more clusters in df1 than df2
    if len(df1_clusters) > len(df2_clusters):
        for s in scores:
            if s['clus2'] not in change_rules.keys():
                change_rules[s['clus2']] = s['clus1']

    # if there are fewer clusters in df1 than df2
    elif len(df1_clusters) < len(df2_clusters):
        for s in scores:
            if s['clus1'] not in change_rules.values():
                change_rules[s['clus2']] = s['clus1']

        # find clusters in df2 for which there are not rules yet
        extra_clusters = []
        for c in df2_clusters:
            if c not in change_rules.keys():
                extra_clusters.append(c)

        # generate collision-free IDs for extra clusters
        max_val = max(change_rules.keys())
        for ec in extra_clusters:
            change_rules[ec] = max_val
            max_val += 1

    # if there are an equal number of clusters in df1 and df2
    else:
        for s in scores:
            if s['clus1'] not in change_rules.keys() and s['clus2'] not in change_rules.values():
                change_rules[s['clus2']] = s['clus1']

    df2['cluster'].replace(change_rules, inplace=True)
    return df2, change_rules


def getDistribution(s):
    clusters = s.df['cluster'].to_list()
    clusters_iter = range(min(clusters), max(clusters) + 1)
    distribution = []
    for i in clusters_iter:
        probability = clusters.count(i) / len(clusters)
        distribution.append(probability)
    return list(zip(list(clusters_iter), distribution))


def alignDistributions(distr1, distr2):
    distrs = [list(distr1), list(distr2)]
    distrs.sort(key=lambda i: len(i))
    clus = lambda i: i[0]
    # if probability distributions are not equal
    if len(distr1) != len(distr2):
        for cluster, probability in distrs[1]:
            # if cluster is not in the smaller distribution
            if cluster not in list(map(clus, distrs[0])):
                # append tuple to smaller distribution of (cluster, 0)
                distrs[0].append((cluster, 0.0))

    # sort distributions by cluster
    distrs[0].sort(key=clus)
    distrs[1].sort(key=clus)

    return distrs[0], distrs[1]


# TODO: documentation
class score:
    def __init__(self, n_clusters: int, clustering_method, silhouetteScore: float, df):
        self.n_clusters = n_clusters
        self.clustering_method = clustering_method
        self.silhouetteScore = silhouetteScore
        self.df = df

    def __str__(self):
        info = ['Number of clusters: ' + str(self.n_clusters),
                'Clustering method: ' + self.clustering_method.__name__,
                'Silhouette Score: ' + str(self.silhouetteScore)]

        return '\n'.join(info)

    def plot(self, formatText=None, tokens=None, save=None, axisDims=None):
        # make plt title information
        n_clusters_str = '# Clusters: ' + str(self.n_clusters)
        clustering_method_str = 'Clustering Method: ' + self.clustering_method.__name__
        silhouette_score_str = 'Silhouette Score: ' + str(np.round(self.silhouetteScore, decimals=4))
        wumSize = '# embeddings: ' + str(len(self.df))

        pads = {'[CLS]', '[SEP]'}
        padsInTokens = pads.intersection(self.tokens)

        df_fields = ['words', 'x', 'y', 'cluster']
        filtered_dict = dict()

        if type(tokens) == list:
            for field in df_fields:
                filtered_dict[field] = [self.df[field].to_list()[x] for x in range(len(self.df))
                                        if self.df['words'][x] in tokens]

            df_to_plot = pd.DataFrame(filtered_dict)

        else:
            df_to_plot = self.df

        # make the plt plot
        right_to_left = lambda i: i[::-1] if (formatText == 'right_to_left' and not padsInTokens) else i
        tokensTitle = tokens
        if tokens:
            plt.suptitle(right_to_left(', '.join(tokensTitle)), size=10)
        plt.scatter(df_to_plot['x'], df_to_plot['y'], c=df_to_plot['cluster'], cmap='copper')
        plt.title('\n' + n_clusters_str + " | " + clustering_method_str + " | " + silhouette_score_str + '\n' + wumSize,
                  fontdict={'fontsize': 9})
        if axisDims is not None:
            plt.axis(axisDims)

        if save is not None:
            filename = save + '.png'
            plt.savefig(filename)

        plt.show()

    def match_clusters(self, other):
        new_DF, change_rules = match(other, self)
        return score(self.n_clusters, self.clustering_method, self.silhouetteScore, new_DF), change_rules


class wum:
    def __init__(self, u, addresses=None, token=None, pcaFirst=False, n_components=2, random_state=10):
        """
        __init__ function for wum

        Parameters
        ----------
        u : np.array
            list of word vectors in np arrays
        token : list
            token that word usage matrix represents
        """

        if token is None:
            token = list()

        # copy constructor -- needs to be updated
        if type(u) == wum:
            self.u = np.array([vec for vec in u.getWUM()])
            self.tokens = [t for t in u.getTokens()]
            self.prototype = u.getPrototype()
            self.addresses = u.addresses

        # default constructor - for WUMs representing single token
        else:
            if pcaFirst:
                pca = PCA(n_components=n_components, random_state=random_state)
                self.u = pca.fit_transform(u)
            else:
                self.u = u

            self.tokens = token  # list so tokens can be added together if WUM represents multiple tokens
            self.prototype = sum(u) / len(u)
            self.pcaFirst = pcaFirst
            self.random_state = random_state
            self.addresses = addresses if addresses else []

    def __add__(self, other):
        u = np.concatenate([self.u, other.getWUM()])
        tokens = self.tokens + other.getTokens()

        return wum(u, tokens)

    def __eq__(self, other):
        return True if np.array_equal(self.u, other.getWUM()) and self.tokens == other.getTokens() else False

    def __gt__(self, other, triangulationPoint=None):
        tPoint = triangulationPoint if triangulationPoint else np.zeros(len(self.prototype))
        return distance.cosine(self.prototype, tPoint) > distance.cosine(other.prototype, tPoint)

    def __lt__(self, other, triangulationPoint=None):
        tPoint = triangulationPoint if triangulationPoint else np.zeros(len(self.prototype))
        return distance.cosine(self.prototype, tPoint) < distance.cosine(other.prototype, tPoint)

    def __len__(self):
        return len(self.u)

    def __str__(self):
        return tabulate(list(zip(self.tokens, self.u)))

    def prototypicalEquivalence(self, other):
        return True if self.prototype == other.prototype else False

    def getWUM(self):
        """

        Returns
        -------
        np.array
            word usage matrix
        """
        return self.u

    def getTokens(self):
        """

        Returns
        -------
        list
            token(s) (list of str) that np array represents
        """
        return self.tokens

    def getPrototype(self):
        """
        Returns prototype of wum object

        The prototype of a word-usage-matrix is the average (vector) of all of the word usage matrix's constituent
        contextualized word embeddings.

        Returns
        -------
        np.array
            prototype of self.u
        """

        return self.prototype

    def prt(self, other_wum):
        """
            Calculates inverted cosine similarity over word prototypes of the wum object and another wum object

            Parameters
            ----------
            other_wum : wum
                another word usage matrix from another time period in a wum object

            Returns
            -------
                Inverted cosine similarity over word prototypes of this and other wum objects
        """

        p1, p2 = self.prototype, other_wum.prototype
        return 1 / (1 - distance.cosine(p1, p2))

    # TODO
    def apd(self, other_wum, sample=None):
        """
        Calculates average pairwise cosine distance between token embeddings of the wum object, given another wum object

        wrapper fn for sklearn.metrics.pairwise.cosine_distances

        Returns
        -------

        """
        averages = []
        bad = False
        u_vecs = random.sample(list(self.u), math.floor(len(self) * sample)) if sample else self.u
        v_vecs = random.sample(list(other_wum.u), math.floor(len(other_wum) * sample)) if sample else other_wum.u

        # sometimes sample size is 0 and that's an issue lol
        if sample and len(u_vecs) == 0 or len(v_vecs) == 0:
            bad = True
            u_vecs = self.u
            v_vecs = other_wum.u

        for u in u_vecs:
            for v in v_vecs:
                averages.append(distance.cosine(u, v))

        return (1 / (len(u_vecs) * len(v_vecs))) * sum(averages)

    def jsd(self, other_wum, clusterMethod=KMeans, returnMetadata=False):
        """
        Calculates Jensen-Shannon Divergence between embedding clusters of the wum object and another wum objects

        Wrapper class for scipy.spatial.distance.jensenshannon

        Returns
        -------
        float
            Jensen-Shannon distance between wum and other wum

        """
        metadata = {}

        self_score = self.cluster(random_state=self.random_state, clusterMethod=clusterMethod, plot=False)[0]
        other_score, change_rules = other_wum.cluster(random_state=self.random_state,
                                                      clusterMethod=clusterMethod, plot=False)[0].match_clusters(
            self_score)

        x, y = alignDistributions(getDistribution(self_score), getDistribution(other_score))

        metadata['w1_score'] = self_score.silhouetteScore
        metadata['w2_score'] = other_score.silhouetteScore
        metadata['w1_n_clusters'] = self_score.n_clusters
        metadata['w2_n_clusters'] = other_score.n_clusters

        x_dist = np.array(list(map(lambda i: i[1], x)))
        y_dist = np.array(list(map(lambda i: i[1], y)))

        jsd = distance.jensenshannon(x_dist, y_dist)
        if returnMetadata:
            return jsd, metadata
        else:
            return jsd

    def div(self, other_wum):
        """
        Calculates difference between token embedding diversities of wum object and another wum object

        Parameters
        ----------
        other_wum : wum
            other wum

        Returns
        -------
        float
            DIV

        """
        if self.pcaFirst:
            p1, p2 = sum(self.u) / len(self.u), sum(other_wum.u) / len(other_wum.u)
        else:
            p1, p2 = self.getPrototype(), other_wum.getPrototype()
        dists_from_p1 = np.array([distance.cosine(vec, p1) for vec in self.u])
        dists_from_p2 = np.array([distance.cosine(vec, p2) for vec in other_wum.getWUM()])
        var_coefficient_1 = np.sum(dists_from_p1) / self.u.size
        var_coefficient_2 = np.sum(dists_from_p2) / other_wum.getWUM().size

        return abs(var_coefficient_1 - var_coefficient_2)

    def get_pca(self, n_components=2):
        """
        Performs principal component analysis of word usage matrix given number of components [dimensionality reduction]

        Parameters
        ----------
        n_components : int
            number of components of desired PCA result


        Returns
        -------
        np.array
            PCA-d word usage matrix

        """
        m = PCA(n_components=n_components, random_state=self.random_state)
        return self.u if self.pcaFirst else m.fit_transform(self.u)

    def auto_silhouette(self, n_candidates=3, pcaDim=2):
        """

        Parameters
        ----------
        n_candidates : int
            specifies top n scorers
        pcaDim : int
            How many dimensions to reduce the word usage matrix to using principal component analysis

        Returns
        -------
            N candidates with top silhouette scores

        """
        warnings.filterwarnings("ignore")

        # define possible clustering methods
        methods = [KMeans, SpectralClustering, AgglomerativeClustering, KMedoids]
        # define random state for consistency
        random_state = 10
        # initiate pca for WUM for the sake of memory lol
        wum_pca = self.u if self.pcaFirst else self.get_pca(n_components=pcaDim)
        bestScores = []

        if len(wum_pca) == 1:
            raise SilhouetteError("You're not going to want to try this with a word usage matrix with only 1 "
                                  "embedding in it.")

        else:
            # you're not going to be able to get a silhouette score on a # of clusters that exceeds the length of self.u
            if len(wum_pca) > 10:
                r = range(2, 11)
            else:
                r = range(2, len(wum_pca) - 1)

            # for i in possible clusters 1-10 (or number of embeddings in the word usage matrix if less than 10):
            for i in r:
                kmeans = KMeans(n_clusters=i, random_state=random_state).fit(wum_pca)
                kmeans_labels = kmeans.labels_

                spectral = SpectralClustering(n_clusters=i, random_state=random_state).fit(wum_pca)
                spectral_labels = spectral.labels_

                agglomerative = AgglomerativeClustering(n_clusters=i).fit(wum_pca)
                agglomerative_labels = agglomerative.labels_

                kmedoids = KMedoids(n_clusters=i, random_state=random_state).fit(wum_pca)
                kmedoids_labels = kmedoids.labels_

                labels = [kmeans_labels, spectral_labels, agglomerative_labels, kmedoids_labels]

                # throwing this into a lambda function so it doesn't have to wrap lol
                getScore = lambda j: (methods[j], silhouette_score(wum_pca, labels[j], random_state=10))

                scores = [getScore(i) for i in range(len(methods))]
                scores.sort(key=lambda j: j[1], reverse=True)
                bestScore = scores[0]
                # append   candidate   score    model
                bestScores.append((i, bestScore[0], bestScore[1]))

            # sort scores by score in descending order
            bestScores.sort(key=lambda k: k[2], reverse=True)

            return bestScores[:n_candidates], wum_pca

    # TODO: documentation
    def silhouette(self, n_candidates=3, pcaDim=2, clusterMethod=KMeans):
        # define possible clustering methods
        needsRandomState = [KMeans, SpectralClustering, KMedoids]
        # define random state for consistency
        random_state = 10
        # initiate pca for WUM for the sake of memory lol
        wum_pca = self.u if self.pcaFirst else self.get_pca(n_components=pcaDim)
        bestScores = []

        if len(wum_pca) == 1:
            raise SilhouetteError("You're not going to want to try this with a word usage matrix with only 1 "
                                  "embedding in it.")

        else:
            # you're not going to be able to get a silhouette score on a # of clusters that exceeds the length of self.u
            if len(wum_pca) > 10:
                r = range(2, 11)
            else:
                r = range(2, len(wum_pca) - 1)

            # for i in possible clusters 1-10 (or number of embeddings in the word usage matrix if less than 10):
            for i in r:
                if clusterMethod in needsRandomState:
                    fit = clusterMethod(n_clusters=i, random_state=random_state).fit(wum_pca)
                else:
                    fit = clusterMethod(n_clusters=i).fit(wum_pca)

                labels = fit.labels_

                s = (clusterMethod, silhouette_score(wum_pca, labels, random_state=10))
                # append   candidate   score    model
                bestScores.append((i, s[0], s[1]))

            # sort scores by score in descending order
            bestScores.sort(key=lambda k: k[2], reverse=True)

            return bestScores[:n_candidates], wum_pca

    def autoCluster(self, n_candidates: int = 1, random_state=None, plot=False, formatText=None):
        """

        Parameters
        ----------
        n_candidates : int
            How many clusters to perform according to the silhouette analysis
        random_state : int
            Specify a random state for consistency
        plot : bool
            True if plotting the clusters is desired
        formatText : str
            Formats right-to-left if 'right_to_left'

        Returns
        -------
        list
            List of dictionaries containing candidate data (structure specified in src code)

        """
        methods = [KMeans, SpectralClustering, AgglomerativeClustering, KMedoids]

        rState = 10 if random_state is None else self.random_state

        candidatesData = []

        for method in methods:
            candidates = self.cluster(n_candidates=n_candidates, clusterMethod=method, random_state=rState, plot=False,
                                      formatText=formatText)

            [candidatesData.append(c) for c in candidates]

        # sort the candidates!
        if n_candidates > 1:
            candidatesData.sort(key=lambda i: i.silhouetteScore, reverse=True)

        # cut off candidates at n_candidates point:
        significant_candidates: list = candidatesData[:n_candidates]

        # plot if needed
        if plot:
            for candData in significant_candidates:
                candData.plot(formatText=formatText)

        return significant_candidates

    # TODO: documentation
    def cluster(self, n_candidates: int = 1, clusterMethod=KMeans, random_state=None, plot=False, formatText=None):
        needsRandomState = [KMeans, SpectralClustering, KMedoids]

        rState = self.random_state if random_state is None else random_state

        candidates, pca = self.silhouette(n_candidates=n_candidates, clusterMethod=clusterMethod)
        candidatesData = []

        for candidate in candidates:
            # if candidate clustering method requires a random state:
            clusteringMethod = candidate[1]
            if clusteringMethod in needsRandomState:
                model = clusteringMethod(n_clusters=candidate[0], random_state=rState).fit(pca)
            else:
                model = clusteringMethod(n_clusters=candidate[0]).fit(pca)

            df = pd.DataFrame({'token': self.tokens,
                               'x': [i[0] for i in pca],
                               'y': [i[1] for i in pca],
                               'cluster': list(model.labels_)})

            candidateData = score(n_clusters=candidate[0], clustering_method=candidate[1], silhouetteScore=candidate[2],
                                  df=df, tokens=set(self.tokens))

            candidatesData.append(candidateData)

        # sort the candidates!
        if n_candidates > 1:
            candidatesData.sort(key=lambda i: i.silhouetteScore, reverse=True)

        # plot if needed
        if plot:
            for candData in candidatesData:
                candData.plot(formatText=formatText)

        return candidatesData

    def asDict(self, jsonFriendly=True):
        """
        Returns wum object as dictionary (use __dict__ if not jsonFriendly)

        Parameters
        ----------
        jsonFriendly : bool
            True if JSON-serializable objects are necessary

        Returns
        -------
        dict
            wum data stored as dictionary

        """
        # lambda function for jsonFriendly conditional
        jsonCond = lambda i: i.tolist() if jsonFriendly else i

        # initialize empty dict
        data = dict()

        # add data members to dict
        data['u'] = [jsonCond(vec) for vec in self.u]
        data['tokens'] = self.tokens

        return data

    def cluster_distributions(self, clusterMethod=KMeans):
        if clusterMethod is None:
            candidate = self.cluster(n_candidates=1)
        else:
            # cluster WUM
            candidate = self.cluster(n_candidates=1, clusterMethod=clusterMethod)[0]

        # get df from cluster analysis
        candidate_df = candidate.df
        clusters = candidate_df['cluster'].to_list()
        size = len(clusters)

        distribution = []
        for cluster in set(clusters):
            distribution.append(float(clusters.count(cluster)) / size)

        return distribution


class wumGen:
    def __init__(self, df: Union[pd.DataFrame, dict], verbose=False, minOccs=1, pcaFirst=False, n_components=2,
                 random_state=10):
        """
        __init__ function for wumGen class

        Constructs and stores word usage matrices of singular words given a Pandas DataFrame

        Parameters
        ----------
        df : pd.DataFrame or dict
            Pandas DataFrame containing 2 columns: 'tokens' and 'embeddings'
        verbose : bool
            Provides status updates on construction of word usage matrices via tqdm package if True
        """

        # dictionary constructor
        if type(df) == dict:
            self.embeddings = df['embeddings']
            self.tokens = df['tokens']

            self.pcaFirst = df['pcaFirst']
            self.n_components = df['n_components']
            self.random_state = df['random_state']

            self.size = df['size']
            self.vocab = df['vocab']
            self.WUMs = df['WUMs']

        # default constructor with pd DataFrame
        else:
            tqdm_cond = lambda i: tqdm(i) if verbose else i
            verboseCond = lambda i: print(i) if verbose else i

            self.embeddings = df['embeddings'].to_list()
            self.tokens = df['tokens'].to_list()

            self.pcaFirst = pcaFirst
            self.n_components = n_components
            self.random_state = random_state

            verboseCond(print('getting vocab info...'))
            self.size = len(self.tokens)
            self.vocab = set(self.tokens)

            verboseCond(print('constructing individual word usage matrices...'))
            try:
                self.WUMs = {tok: self.getWordUsageMatrix_Individual(tok, init=True) for tok in tqdm_cond(self.vocab)
                             if self.tokens.count(tok) >= minOccs}
            except ValueError:
                print('Hapax legomena need to be removed from this corpus before PCA can be applied.' +
                      '\nSetting pcaFirst to False...')
                self.pcaFirst = False
                self.WUMs = {tok: self.getWordUsageMatrix_Individual(tok) for tok in tqdm_cond(self.vocab)
                             if self.tokens.count(tok) >= minOccs}

    def __len__(self):
        return self.size

    def __add__(self, other):
        if not (self.pcaFirst == other.pcaFirst and self.n_components == other.n_components):
            raise pcaError
        else:
            new_wumGen_dict = dict()
            new_wumGen_dict['embeddings'] = self.embeddings + other.embeddings
            new_wumGen_dict['tokens'] = self.tokens + other.tokens

            new_wumGen_dict['pcaFirst'] = self.pcaFirst
            new_wumGen_dict['n_components'] = self.n_components
            new_wumGen_dict['random_state'] = self.random_state

            new_wumGen_dict['size'] = self.size + other.size
            new_wumGen_dict['vocab'] = set.union(self.vocab, other.vocab)

            otherWUMs = other.WUMs.items()
            newWUMs = dict()

            for tok, w in self.WUMs.items():
                newWUMs[tok] = w if tok not in otherWUMs else w + otherWUMs[tok]

            new_wumGen_dict['WUMs'] = newWUMs

        return wumGen(new_wumGen_dict)

    def __iter__(self):
        return iter(self.WUMs)

    def getTokens(self):
        """
        Accessor for tokens data member

        Returns
        -------
        list
            tokens for embeddings contained by word usage matrix in self.WUMs of key 'token'
        """

        return self.tokens

    def getSize(self):
        """
        Accessor for size data member

        Returns
        -------
        int
            Number of WUMs in object (equal to number of unique tokens in the df argument of the constructor)
        """

        return self.size

    def getWUMs(self):
        """
        Accessor for WUMs data member

        Returns
        -------
        dict
            WUMs with given their representative token as their key
        """

        return self.WUMs

    def getWordUsageMatrix_Individual(self, token, init=False):
        """
        Accessor for an individual word usage matrix stored in self.WUMs data member

        Parameters
        ----------
        token : str
            A given token

        Returns
        -------
        wum
            word usage matrix of given token
        init
            whether to use at initial loading
        """
        if init:
            vecs = [self.embeddings[i] for i in range(len(self.embeddings)) if self.tokens[i] == token]

            try:
                return wum(np.array(vecs), [token] * len(vecs), pcaFirst=self.pcaFirst, n_components=self.n_components,
                           random_state=self.random_state)

            except KeyError:
                print('word usage matrix of given token not found in object!: ' + token)
        else:
            try:
                return self.WUMs[token]
            except KeyError:
                print('word usage matrix of given token not found in object!: ' + token)

    def findNearestNeighbors(self, w: wum, n_neighbors=1, ignoreTokens: list = None):
        """
        Finds tokens with nearest WUM prototypes using cosine distance.

        :param w: a given WUM
        :param n_neighbors: number of desired neighbors
        :param ignoreTokens: list of tokens to ignore (e.g., [CLS], [SEP], etc.)
        :return: List of tuples of structure (WUM, cosine distance)
        """

        prototype = lambda i: i.getPrototype() if type(i) == wum else self.WUMs[i].getPrototype()

        def cond(u):
            # prototypical equivalence
            if not np.array_equal(prototype(u), prototype(w)):
                # if token is not in ignoreTokens list/set/whatever | also w is a global var in master fn
                ignoreTokens_intersection = len(set.intersection(set(ignoreTokens), set(w.getTokens()))) == 0
                ignoreTokens_qualifier = ignoreTokens and not ignoreTokens_intersection
                return True if ignoreTokens_qualifier or not ignoreTokens else False
            else:
                return False

        distances = ((u, u.prt(w)) for token, u in self.WUMs.items() if cond(u))

        distances = sorted(distances, key=lambda i: i[1])

        return distances[:n_neighbors]

    # TODO: update documentation
    def autoCluster_analysis(self, n_candidates=1, plot=False, formatText=None, minWUMLength=2, verbose=False):
        tqdm_cond = lambda i: tqdm(list(i)) if verbose else i
        print_cond = lambda i: print(i) if verbose else i

        """
        This performs an autoCluster analysis on all of the WUMs stored in the wumGen object

        :param n_candidates: int
            Number of candidates per autoCluster
        :param random_state: int
            Random state to use
        :param plot: bool
            Whether to plot
        :param minWUMLength: int
            Minimum number of embeddings in each WUM to perform autoCluster on
        :param n_neighbors: int
            # number of neighbors to cluster with
        :param plot_with_neighbors: bool
            Whether to plot with neighbors
        :return:
            A dictionary of autoClustered WUMs, with tokens as keys
        """
        data = {}

        print_cond('Filtering word usage matrices...')
        WUMs_over_threshold = ((t, w) for t, w in self.WUMs.items() if len(w) >= minWUMLength)

        print_cond('Clustering...')
        for t, w in tqdm_cond(WUMs_over_threshold):
            try:
                data[t] = w.autoCluster(n_candidates, plot=plot, formatText=formatText)

            except SilhouetteError:
                print(SilhouetteError)
                print('Token(s) that had the issue: ' + w.getTokens())

        return data

    # TODO: documentation
    def cluster_analysis(self, clusterMethod=KMeans, n_candidates=1, plot=False,
                         formatText=None, minWUMLength=2, verbose=False):

        tqdm_cond = lambda i: tqdm(list(i)) if verbose else i
        print_cond = lambda i: print(i) if verbose else i

        data = {}

        print_cond('Filtering word usage matrices...')
        WUMs_over_threshold = ((t, w) for t, w in self.WUMs.items() if len(w) >= minWUMLength)

        print_cond('Clustering...')
        for t, w in tqdm_cond(WUMs_over_threshold):
            try:
                data[t] = w.cluster(n_candidates, clusterMethod=clusterMethod,
                                    plot=plot, formatText=formatText)

            except SilhouetteError:
                print(SilhouetteError)
                print('Token(s) that had the issue: ' + w.getTokens())

        return data

    def getFreqDist(self, asDF=False):
        """
        Wrapper function for nltk FreqDist
        :param asDF: If desired format is pd dataframe
        :return: frequency list of tokens in wumGen
        """
        pdCond = lambda i: i if not asDF else pd.DataFrame(i.items(), columns=['Token', 'Count'])
        return pdCond(FreqDist(self.tokens))
