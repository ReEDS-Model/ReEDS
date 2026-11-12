# Imports
import os
import sys
import io
import numpy as np
from glob import glob
import pandas as pd
import matplotlib.pyplot as plt

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if 'runs' in reeds_path.split(os.path.sep):
    reeds_path = reeds_path[: reeds_path.index(os.sep + 'runs' + os.sep)]

### Globals
SLIDE_HEIGHT = 6.88
SLIDE_WIDTH = 13.33


#%% ===========================================================================
### --- Powerpoint Tools ---
### ===========================================================================
def init_pptx(
    fpath_template=os.path.join(reeds_path, 'postprocessing', 'template.pptx'),
):
    import pptx
    
    prs = pptx.Presentation(fpath_template)
    return prs

def add_to_pptx(
        title=None,
        prs=None,
        file=None,
        left=0,
        top=0.62,
        width=SLIDE_WIDTH,
        height=None,
        verbose=1,
        slide=None,
        layout=3,
    ):
    """Add current matplotlib figure (or file if specified) to new powerpoint slide"""
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    if not file:
        image = io.BytesIO()
        plt.savefig(image, format='png')
    else:
        image = file
        if not os.path.exists(image):
            raise FileNotFoundError(image)

    if prs is None:
        prs = init_pptx()

    if slide is None:
        # Construct slide and format slide title to fit in shape
        slide = prs.slides.add_slide(prs.slide_layouts[layout])
        title_shape = slide.shapes.title
        title_shape.text = title
        title_shape.text_frame.word_wrap = True
        title_shape.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        title_shape.text_frame.paragraphs[0].runs[0].font.size = Pt(34)
    slide.shapes.add_picture(
        image,
        left=(None if left is None else Inches(left)),
        top=(None if top is None else Inches(top)),
        width=(None if width is None else Inches(width)),
        height=(None if height is None else Inches(height)),
    )
    if verbose:
        print(title)
    return slide

def add_textbox(
        text,
        slide,
        left=0,
        top=7.2,
        width=SLIDE_WIDTH,
        height=0.3,
        fontsize=14,
    ):
    """Add a textbox to the specified slide"""
    from pptx.util import Inches, Pt

    textbox = slide.shapes.add_textbox(
        left=(None if left is None else Inches(left)),
        top=(None if top is None else Inches(top)),
        width=(None if width is None else Inches(width)),
        height=(None if height is None else Inches(height)),
    )
    p = textbox.text_frame.paragraphs[0]
    run = p.add_run()
    run.text = text
    font = run.font
    font.size = Pt(fontsize)
    return slide


#%% ===========================================================================
### --- Tools to get cases
### ===========================================================================
def parse_caselist(caselist, casenames, basecase_in, titleshorten=0):
    use_table_casenames = False
    use_table_colors = False
    use_table_bases = False
    multibase = False
    _caselist = caselist.copy()
    _casenames = casenames
    if len(_caselist) == 1:
        ## If it's a .csv, read the cases to compare
        if _caselist[0].endswith('.csv'):
            dfcase = pd.read_csv(_caselist[0], header=None, comment='#', quoting=3)
            ## First check it's a simple csv with one case per row
            if dfcase.shape[1] == 1:
                caselist = dfcase[0].tolist()
            ## Then check if it's a csv with [casepath,casename] in the header
            elif (
                ('casepath' in dfcase.loc[0].tolist())
                and ('casename' in dfcase.loc[0].tolist())
            ):
                dfcase = dfcase.T.set_index(0).T
                ## Drop cases that haven't finished yet
                unfinished = dfcase.loc[
                    ~dfcase.casepath.map(
                        lambda x: os.path.isfile(os.path.join(x,'outputs','outputs.h5')))
                ].index
                if len(unfinished):
                    print('The following cases have not yet finished:')
                    print('\n'.join(dfcase.loc[unfinished].casepath.tolist()))
                dfcase = dfcase.drop(unfinished).copy()
                caselist = dfcase.casepath.tolist()
                use_table_casenames = True
                if 'color' in dfcase:
                    if not dfcase.color.isnull().any():
                        use_table_colors = True
                # Single base case: If missing or empty 'base' column, fill with 'casename' of first listed case
                if ('base' not in dfcase) or (dfcase.base.isnull().all()):
                    dfcase['base'] = dfcase.loc[1,'casename']
                # Multibase case: Fill any empty 'base' values with the cases' corresponding 'casename' values
                elif dfcase.base.isnull().any():
                    dfcase['base'] = dfcase['base'].fillna(dfcase['casename'])
                    multibase = True
                
            ## Otherwise assume it's a copy of a cases_{batchname}.csv file in a case folder
            ## This approach is less robust; the others are preferred.
            else:
                prefix_plus_tail = os.path.dirname(_caselist[0])
                tails = [i for i in dfcase.iloc[0] if i not in ['Default Value',np.nan]]
                prefix = prefix_plus_tail[:-len([i for i in tails if prefix_plus_tail.endswith(i)][0])]
                caselist = [prefix+i for i in tails]
        ## Otherwise look for all runs starting with the provided string
        else:
            caselist = sorted(glob(_caselist[0]+'*'))
            ## If no titleshorten is provided, use the provided prefix
            if not titleshorten:
                titleshorten = len(os.path.basename(_caselist))
    else:
        caselist = _caselist

    ## Remove cases that haven't finished yet
    caselist = [
        i for i in caselist
        if os.path.isfile(os.path.join(i,'outputs','outputs.h5'))
    ]

    ## Get the casenames
    if use_table_casenames:
        casenames = [c.replace('\\n','\n') for c in dfcase.casename.tolist()]
    else:
        casenames = (
            _casenames.split(',') if len(_casenames)
            else [os.path.basename(c)[titleshorten:] for c in caselist]
        )

    if len(caselist) != len(casenames):
        err = (
            f"len(caselist) = {len(caselist)} but len(casenames) = {len(casenames)}\n\n"
            'caselist:\n' + '\n'.join(caselist) + '\n\n'
            'casenames:\n' + '\n'.join(casenames) + '\n'
        )
        raise ValueError(err)

    cases = dict(zip(casenames, caselist))

    # check to ensure there are at least two cases
    if len(cases) <= 1: 
        err = f"There are less than two cases being compared: {', '.join(cases.values())}"
        raise ValueError(err)
    
    # check to ensure basecase is not defined for multibase comparison
    if (len(basecase_in) > 0) & multibase:
        err = (f"A basecase argument was provided for a multibase comparison. Either remove "
                "the basecase argument from compare_cases.py call or delete the base column "
                "in the input csv." 
        )
        raise ValueError(err)
        
    ### Get the base cases, overriding base column of dfcase if basecase_in is defined
    if (len(basecase_in) > 0):
        basepath = [c for c in cases.values() if c.endswith(basecase_in)]
        if len(basepath) == 0:
            err = (
                f"Use a basecase that matches one case.\nbasecase={basecase_in} matches none of:\n"
                + '\n'.join(basepath)
            )
            raise ValueError(err)
        elif len(basepath) > 1:
            err = (
                f"Use a basecase that only matches one case.\nbasecase={basecase_in} matches:\n"
                + '\n'.join(basepath)
            )
            raise ValueError(err)
        else:
            basepath = basepath[0]
            ## basecase is the short name; basepath is the full path
            basecase = casenames[caselist.index(basepath)]
            ## Put it first in the list
            cases = {**{basecase:cases[basecase]}, **{k:v for k,v in cases.items() if k != basecase}}
            ## Override base column of dfcase
            dfcase['base'] = basecase
    else:
        ### If using multibase comparison, basecase variable is unused; arbitrarily set to 
        ### the casename of first instance where casename == basecase
        if multibase:
            basecase = dfcase.loc[dfcase['casename'] == dfcase['base']].iloc[0]['casename']
        else:
            basecase = dfcase.loc[1,'base']

    ## Make case->base dictionary, putting basecase first in the list if not multibase
    basemap = dfcase.set_index('casename').base.to_dict()
    if not multibase:
        basemap = {**{basecase:basemap[basecase]}, **{k:v for k,v in basemap.items() if k != basecase}}

    ## Get the colors
    if use_table_colors:
        colors = dict(zip(dfcase.casename, dfcase.color))
        for k, v in colors.items():
            if v.startswith('plt.cm.') or v.startswith('cmocean.cm.'):
                colors[k] = eval(v)
    else:
        colors = reeds.plots.rainbowmapper(cases)

    ## Take a look
    print('Analyzing the following cases:')
    maxpathlength = len(max(cases.values(), key=len))
    for case, path in cases.items():
        print(
            ('(base) ' if (case == basemap[case]) else '       ')
            + f'{path.ljust(maxpathlength)} -> {case}'
        )

    return cases, colors, basecase, basemap, multibase
