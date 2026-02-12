## Compound Triangle Rectangle Sharp Crested (CTRSC) weir calculation
## Discussion of âDesign and Calibration of a Compound Sharp-Crested Weirâ by J. MartÃ­nez, J. Reca, M. T. Morillas, and J. G. LÃ³pez,â, 2005

import math

@MEASUREMENT
def CTRSC_compound_weir(US_Level_in):
    ## Get weir dimensions from sheet
    vnotch_in = 12.0  # Height of v-notch to weir crest (h2)
    b2 = 12.0         # Width of v-notch (= to h2)
    b1 = 108.0        # Width of weir crest
    c1 = 2.0          # Width of overtopping crest left
    c2 = 2.0          # Width of overtopping crest right
    h1_in = 2.0       # Height from weir crest to overtopping crest

    ## Convert to meters
    vnotch_m = vnotch_in * 0.0254
    width_m = (b1 + b2) * 0.0254
    c1_m = c1 * 0.0254
    c2_m = c2 * 0.0254
    h1_m = h1_in * 0.0254

    ## Calculate weir geometry for equation
    b2_cm = b2 * 2.54
    b1_cm = b1 * 2.54
    b1_m, b2_m = b1_cm / 100, b2_cm / 100

    ## Constants
    Ctd, Crd = 0.579, 0.590

    ## Format equation inputs
    h2_m = US_Level_in * 0.0254  # Height above V-notch
    h2_eff_m = h2_m + 0.0008     # Effective head
    h1_m_above_crest = max(h2_m - vnotch_m, 0)  # Height above horizontal crest
    h1_eff_m = max(h1_m_above_crest + 0.0008, 0)  # Effective head

    ## Calculate discharge for compound weir
    Flow_m3s_ctrsc = (
        (8. / 15.) * Ctd * ((2. * 9.81) ** 0.5) * math.tan(math.radians(90.) / 2.) * (h2_eff_m ** 2.5 - h1_eff_m ** 2.5)
        + (2. / 3.) * Crd * ((2. * 9.81) ** 0.5) * (2 * b1_m) * (h1_m_above_crest ** 1.5)
    )

    ## Convert from m^3/s to gpm
    Flow_gpm_ctrsc = Flow_m3s_ctrsc * 15850.372483753
    
    return round(Flow_gpm_ctrsc, 3)


