""" cluster.py

Module containing classes and functions used to cluster fibers and modify
parameters pertaining to clusters.

"""

import numpy as np
import scipy.cluster
import fibers, distance, scalars
import vtk
from joblib import Parallel, delayed
import sklearn.cluster, sklearn.preprocessing

class Cluster:
    """ Clustering of whole-brain tractography data from subject using normalized, random
    walk Laplacian"""

def spectralClustering(inputVTK, scalarData=None, scalarType=None, k_clusters=3, no_of_eigvec=20,                           sigma=60, no_of_jobs=2):
        """
        Clustering of fibers based on pairwise fiber similarity

            INPUT:
                inputVTK - input polydata file
                k_clusters - number of clusters via k-means clustering
                sigma - width of kernel; adjust to alter sensitivity
                no_of_jobs - processes to use to perform computation

        TODO: weighted quantitative clustering
        """
        
        if no_of_eigvec == 1:
            print "Clustering cannot be performed with single eigenvector!"
            return

        noFibers = inputVTK.GetNumberOfLines()
        if noFibers == 0:
            print "ERROR: Input data has 0 fibers!"
            return
        else:
            print "Starting clustering..."
            print "No. of fibers:", noFibers
            print "No. of clusters:", k_clusters

        # 1. Compute similarty matrix
        W = _pairwiseSimilarity_matrix(inputVTK, sigma, no_of_jobs)
        #W = _pairwiseQSimilarity_matrix(inputVTK, scalarData, scalarType, sigma, no_of_jobs)

        # 2. Compute degree matrix
        D = _degreeMatrix(W)

        # 3. Compute unnormalized Laplacian
        L = D - W

        # 4. Compute normalized Laplacian (random-walk)
        Lrw = np.dot(np.diag(np.divide(1, np.sum(D, 0))), L)

        # 5. Compute eigenvalues and eigenvectors of generalized eigenproblem
        # vectors are columns ([:, n]) of matrix
        eigval, eigvec = np.linalg.eig(Lrw)

        # 6. Compute information for clustering using "N" number of smallest eigenvalues
        # Skip first eigenvector, no information provided for clustering???
        U = eigvec[:, 0:no_of_eigvec]

        # 7. Find clusters using K-means clustering
        # Sort centroids by eigenvector order
        centroids, clusterIdx = scipy.cluster.vq.kmeans2(U.astype('float'), k_clusters, minit='points')
        centroid_order = np.argsort(centroids[:,0])

        if no_of_eigvec == 2:
            colour = _cluster_to_rgb(U)
        else: 
            colour = _cluster_to_rgb(centroids)

        # 8. Return results
        outputData = inputVTK
        outputPolydata = _format_outputVTK(outputData, clusterIdx, colour, U)

        return outputPolydata, clusterIdx, colour, centroids

def _pairwiseDistance_matrix(inputVTK, sigma, no_of_jobs):
    """ An internal function used to compute an NxN distance matrix for all
    fibers (N) in the input data

    INPUT:
        inputVTK - input polydata file
        sigma - width of kernel; adjust to alter sensitivity
        no_of_jobs - processes to use to perform computation

    OUTPUT:
        distances - NxN matrix containing distances between fibers
    """

    fiberArray = fibers.FiberArray()
    fiberArray.convertFromVTK(inputVTK, pts_per_fiber=20)

    distances = Parallel(n_jobs=no_of_jobs, verbose=0)(
            delayed(distance.fiberDistance)(fiberArray.getFiber(fidx),
                    fiberArray)
            for fidx in range(0, fiberArray.no_of_fibers))

    distances = np.array(distances)
    # Normalize between 0 and 1
    distances = sklearn.preprocessing.MinMaxScaler().fit_transform(distances)

    return distances

def _pairwiseSimilarity_matrix(inputVTK, sigma, no_of_jobs):
    """ An internal function used to compute an NxN similarity matrix for all
    fibers (N) in the input data.

    INPUT:
        inputVTK - input polydata file
        sigma - width of kernel; adjust to alter sensitivity
        no_of_jobs - proccesses to use to perform computation

    OUTPUT:
        similarity - NxN matrix containing similarity between fibers
    """

    distances = _pairwiseDistance_matrix(inputVTK, sigma, no_of_jobs)

    sigmasq = np.square(sigma)
    similarities = distance.gausKernel_similarity(distances, sigmasq)

    similarities = np.array(similarities)

    return similarities

def _pairwiseQDistance_matrix(inputVTK, scalarData, scalarType, no_of_jobs):
    """ An internal function used to compute the "distance" between quantitative
    points along a fiber. """

    fiberArray = fibers.FiberArray()
    fiberArray.convertFromVTK(inputVTK, pts_per_fiber=20)
    no_of_fibers = fiberArray.no_of_fibers
    scalarArray = scalars.FiberArrayScalar()
    scalarArray.addScalar(inputVTK, fiberArray, scalarData, scalarType)

    qDistances = Parallel(n_jobs=no_of_jobs, verbose=0)(
            delayed(distance.scalarDistance)(
                scalarArray.getScalar(fiberArray, fidx, scalarType),
                scalarArray.getScalars(fiberArray, range(no_of_fibers), scalarType))
            for fidx in range(0, no_of_fibers)
    )
	
    qDistances = np.array(qDistances)
   
    # Normalize if not already normalized between 0 and 1 
    if np.max(qDistances) > 1.0:
        qDistances = sklearn.preprocessing.MinMaxScaler().fit_transform(qDistances)

    return qDistances

def _pairwiseQSimilarity_matrix(inputVTK, scalarData, scalarType, sigma, no_of_jobs):
    """ An internal function used to compute the cross-correlation between
    quantitative metrics along a fiber.

    INPUT:
        inputVTK - input polydata file
        no_of_jobs - processes to use to perform computation

    OUTPUT:
        qSimilarity - NxN matrix containing correlation values between fibers
    """

    qDistances = _pairwiseQDistance_matrix(inputVTK, scalarData, scalarType, no_of_jobs)

    sigmasq = np.square(sigma)
    qSimilarity = distance.gausKernel_similarity(qDistances, sigmasq)

    qSimilarity = np.array(qSimilarity)

    return qSimilarity

def _degreeMatrix(inputMatrix):
    """ An internal function used to compute the Degree matrix, D """

    # Determine the degree matrix
    degMat = np.diag(np.sum(inputMatrix, 0))

    return degMat

def _cluster_to_rgb(data):
    
    """ Generate cluster color from first three components of data """ 

    colour = data[:, 0:3]

    # Normalize color
    colour_len = np.sqrt(np.sum(np.power(colour, 2), 1))
    colour = np.divide(colour.T, colour_len).T

    # Convert range from 0 to 255
    colour = 127.5 + (colour * 127.5)

    return colour

def _format_outputVTK(polyData, clusterIdx, colour, data):
    """ Output polydata with colours, cluster numbers and coordinates """

    dataColour = vtk.vtkUnsignedCharArray()
    dataColour.SetNumberOfComponents(3)
    dataColour.SetName('DataColour')

    #dataCoord = vtk.vtkFloatArray()
    #dataCoord.SetNumberOfComponents(data.shape[1])
    #dataCoord.SetName('DataCoordinates')

    clusterColour = vtk.vtkIntArray()
    clusterColour.SetName('ClusterNumber')

    for fidx in range(0, polyData.GetNumberOfLines()):
        dataColour.InsertNextTuple3(
                colour[clusterIdx[fidx], 0], colour[clusterIdx[fidx], 1], colour[clusterIdx[fidx], 2])
        clusterColour.InsertNextTuple1(int(clusterIdx[fidx]))
        #dataCoord.InsertNextTupleValue(data[fidx, :])

    polyData.GetCellData().AddArray(dataColour)
    #polyData.GetCellData().AddArray(dataCoord)
    polyData.GetCellData().AddArray(clusterColour)

    polyData.GetPointData().SetScalars(dataColour)

    return polyData
