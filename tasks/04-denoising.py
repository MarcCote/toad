import os

import dipy.denoise.noise_estimate
import dipy.denoise.nlmeans
import nibabel
import numpy

from core.generictask import GenericTask
from lib.images import Images
from lib import util


__author__ = 'desmat'

class Denoising(GenericTask):


    def __init__(self, subject):
        GenericTask.__init__(self, subject, 'eddy', 'preparation', 'parcellation', 'fieldmap', 'qa')
        self.matlabWarning = False


    def implement(self):
        if self.get("algorithm").lower() in "none":
            self.info("Skipping denoising process")

        else:
            dwi = self.__getDwiImage()
            target = self.buildName(dwi, "denoise")
            if self.get("algorithm") == "nlmeans":

                dwiImage = nibabel.load(dwi)
                dwiData  = dwiImage.get_data()

                sigma, maskNoise = self.__computeSigmaAndNoiseMask(dwiData)
                self.info("sigma value that will be apply into nlmeans = {}".format(sigma))
                denoisingData = dipy.denoise.nlmeans.nlmeans(dwiData, sigma)
                nibabel.save(nibabel.Nifti1Image(denoisingData.astype(numpy.float32), dwiImage.get_affine()), target)
                nibabel.save(nibabel.Nifti1Image(maskNoise.astype(numpy.float32),
                                                 dwiImage.get_affine()), self.buildName(target, "noise_mask"))

                #QA
                noiseMask = self.getImage(self.workingDir, "noise_mask")
                noiseMaskPng = self.buildName(noiseMask, None, 'png')
                #@TODO remplacer dwi par une b0
                self.slicerPng(dwi, noiseMaskPng, maskOverlay=noiseMask)
                sigmaPng = self.buildName(dwi, 'sigma', 'png')
                self.plotSigma(sigma, sigmaPng)


            elif self.get('general', 'matlab_available'):
                dwi = self.__getDwiImage()
                dwiUncompress = self.uncompressImage(dwi)

                tmp = self.buildName(dwiUncompress, "tmp", 'nii')
                scriptName = self.__createMatlabScript(dwiUncompress, tmp)
                self.__launchMatlabExecution(scriptName)

                self.info("compressing {} image".format(tmp))
                tmpCompress = util.gzip(tmp)
                self.rename(tmpCompress, target)

                if self.get("cleanup"):
                    self.info("Removing redundant image {}".format(dwiUncompress))
                    os.remove(dwiUncompress)
            else:
                self.matlabWarning = True
                self.warning("Algorithm {} is set but matlab is not available for this server.\n"
                             "Please configure matlab or set denoising algorithm to nlmeans or none"
                             .format(self.get("algorithm")))

            #QA
            workingDirDwi = self.getImage(self.workingDir, 'dwi', 'denoise')
            if workingDirDwi:
                #@TODO  remove comments --add a method to get the correct mask
                dwiGif = self.buildName(workingDirDwi, None, 'gif')
                dwiCompareGif = self.buildName(workingDirDwi, 'compare', 'gif')
                brainMask = self.getImage(self.dependDir, 'mask_eddy')
                self.slicerGif(workingDirDwi, dwiGif, boundaries=brainMask)
                self.slicerGifCompare(dwi, workingDirDwi, dwiCompareGif, boundaries=brainMask)


    def __getDwiImage(self):
        if self.getImage(self.fieldmapDir, "dwi", 'unwarp'):
            return self.getImage(self.fieldmapDir, "dwi", 'unwarp')
        elif self.getImage(self.dependDir, "dwi", 'eddy'):
            return self.getImage(self.dependDir, "dwi", 'eddy')
        else:
            return self.getImage(self.preparationDir, "dwi")


    def __createMatlabScript(self, source, target):

        scriptName = os.path.join(self.workingDir, "{}.m".format(self.get("script_name")))
        self.info("Creating denoising script {}".format(scriptName))
        tags={ 'source': source,
               'target': target,
               'workingDir': self.workingDir,
               'beta': self.get('beta'),
               'rician': self.get('rician'),
               'nbthreads': self.getNTreadsDenoise()}

        if self.get("algorithm") == "aonlm":
            template = self.parseTemplate(tags, os.path.join(self.toadDir, "templates", "files", "denoise_aonlm.tpl"))
        else:
            template = self.parseTemplate(tags, os.path.join(self.toadDir, "templates", "files", "denoise_lpca.tpl"))

        util.createScript(scriptName, template)
        return scriptName


    def __launchMatlabExecution(self, pyscript):

        self.info("Launch DWIDenoisingLPCA from matlab.")
        self.launchMatlabCommand(pyscript, None, None, 10800)


    def __computeSigmaAndNoiseMask(self, data):
        """Use piesno algorithm to estimate sigma and noise

        Args:
            data: A dMRI 4D matrix

        Returns:
            a float representing sigma "The estimated standard deviation of the gaussian noise"
            and a mask identyfing all the pure noise voxel that were found.
        """

        try:
            numberArrayCoil = int(self.get("number_array_coil"))
        except ValueError:
            numberArrayCoil = 1
        sigmaMatrix = numpy.zeros_like(data, dtype=numpy.float32)
        sigmaVector = numpy.zeros(data.shape[2], dtype=numpy.float32)
        maskNoise = numpy.zeros(data.shape[:-1], dtype=numpy.bool)


        for idx in range(data.shape[2]):
            sigmaMatrix[:, :, idx], maskNoise[:, :, idx] = dipy.denoise.noise_estimate.piesno(data[:, :, idx],
                                                                                         N=numberArrayCoil,
                                                                                         return_mask=True)
            sigmaVector[idx] = sigmaMatrix[0,0,idx,0]
        return numpy.median(sigmaVector), maskNoise




    def isIgnore(self):
        return (self.get("algorithm").lower() in "none") or (self.get("ignore"))


    def meetRequirement(self, result = True):
        images = Images((self.getImage(self.fieldmapDir, "dwi", 'unwarp'), 'fieldmap'),
                       (self.getImage(self.dependDir, "dwi", 'eddy'), 'eddy corrected'),
                       (self.getImage(self.preparationDir, "dwi"), 'diffusion weighted'))

        #@TODO add those image as requierement
        #norm = self.getImage(self.parcellationDir, 'norm')
        #noiseMask = self.getImage(self.parcellationDir, 'noise_mask')
        return images.isAtLeastOneImageExists()


    def isDirty(self):
        return Images((self.getImage(self.workingDir, "dwi", 'denoise'), 'denoised'))
                       #(self.getImage(self.workingDir, "noise_mask", 'denoise'), 'denoised'))

    def qaSupplier(self):
        denoiseGif = self.getImage(self.workingDir, 'dwi', 'denoise', ext='gif')
        compareGif = self.getImage(self.workingDir, 'dwi', 'compare', ext='gif')

        images = Images((denoiseGif,'Denoised diffusion image'),
                        (compareGif,'Before and after denoising'),
                       )

        message = 'Algorithm {} is set'.format(self.get("algorithm"))
        if self.matlabWarning:
            message += ' but matlab is not available on this server'
        images.setInformation(message)

        tags = (
            ('sigma', 'Sigmas from nlmean'),
            ('noise_mask', 'Noise mask from nlmean'),
            )

        for prefix, description in tags:
            pngImage = self.getImage(self.workingDir, prefix, ext='png')
            if pngImage:
                images.extend(Images((pngImage, description)))

        return images
