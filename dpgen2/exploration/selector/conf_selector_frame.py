import dpdata
import numpy as np
from collections import Counter
from typing import (
    List,
    Tuple,
)
from pathlib import Path
from . import (
    ConfSelector,
    ConfFilters,
)
from dpgen2.exploration.report import ExplorationReport, TrajsExplorationReport

class ConfSelectorLammpsFrames(ConfSelector):
    """Select frames from trajectories as confs.

    Parameters:
    trust_level: TrustLevel
        The trust level
    conf_filter: ConfFilters
        The configuration filter

    """
    def __init__(
            self,
            trust_level,
            max_numb_sel : int = None,
            conf_filters : ConfFilters = None,
    ):
        self.trust_level = trust_level
        self.max_numb_sel = max_numb_sel
        self.conf_filters = conf_filters
        self.report = TrajsExplorationReport()
    
    def select (
            self,
            trajs : List[Path],
            model_devis : List[Path],
            traj_fmt : str = 'lammps/dump',
            type_map : List[str] = None,
    ) -> Tuple[List[ Path ], ExplorationReport]:
        """Select configurations

        Parameters
        ----------
        trajs : List[Path]
                A `list` of `Path` to trajectory files generated by LAMMPS
        model_devis : List[Path]
                A `list` of `Path` to model deviation files generated by LAMMPS.
                Format: each line has 7 numbers they are used as
                # frame_id  md_v_max md_v_min md_v_mean  md_f_max md_f_min md_f_mean
                where `md` stands for model deviation, v for virial and f for force
        traj_fmt : str
                Format of the trajectory, by default it is the dump file of LAMMPS
        type_map : List[str]
                The `type_map` of the systems

        Returns
        -------
        confs : List[Path]
                The selected confgurations, stored in a folder in deepmd/npy format, can be parsed as dpdata.MultiSystems. The `list` only has one item.
        report : ExplorationReport
                The exploration report recoding the status of the exploration. 

        """
        ntraj = len(trajs)
        assert(ntraj == len(model_devis))
        self.v_level = ( (self.trust_level.level_v_lo is not None) and \
                         (self.trust_level.level_v_hi is not None) )
        self.report.clear()

        for ii in range(ntraj):
            self.record_one_traj(trajs[ii], model_devis[ii], traj_fmt, type_map)

        id_cand = self.report.get_candidates(self.max_numb_sel)
        id_cand_list = [[] for ii in range(ntraj)]
        for ii in id_cand:
            id_cand_list[ii[0]].append(ii[1])

        ms = dpdata.MultiSystems(type_map=type_map)
        for ii in range(ntraj):
            if len(id_cand_list[ii]) > 0:
                ss = dpdata.System(trajs[ii], fmt=traj_fmt, type_map=type_map)
                ss = ss.sub_system(id_cand_list[ii])        
                ms.append(ss)
            
        out_path = Path('confs')
        out_path.mkdir(exist_ok=True)
        ms.to_deepmd_npy(out_path)

        return [out_path], self.report
        

    def record_one_traj(
            self,
            traj, 
            model_devi,
            traj_fmt, 
            type_map,
    )->None:
        ss = ConfSelectorLammpsFrames._load_traj(traj, traj_fmt, type_map)
        mdf, mdv = ConfSelectorLammpsFrames._load_model_devi(model_devi)
        id_f_cand, id_f_accu, id_f_fail = ConfSelectorLammpsFrames._get_indexes(
            mdf, self.trust_level.level_f_lo, self.trust_level.level_f_hi)
        if self.v_level:
            id_v_cand, id_v_accu, id_v_fail = ConfSelectorLammpsFrames._get_indexes(
                mdv, self.trust_level.level_v_lo, self.trust_level.level_v_hi)
        else :
            id_v_cand = id_v_accu = id_v_fail = None
        self.report.record_traj(
            id_f_accu, id_f_cand, id_f_fail,
            id_v_accu, id_v_cand, id_v_fail,
        )

                
    @staticmethod
    def _get_indexes(
            md, 
            level_lo,
            level_hi,
    ):
        id_cand = np.where(np.logical_and(md >=level_lo, md < level_hi))[0]
        id_accu = np.where(md < level_lo)[0]
        id_fail = np.where(md >=level_hi)[0]
        return id_cand, id_accu, id_fail

    @staticmethod
    def _load_traj(
            fname : Path,
            fmt : str,
            type_map : List[str],
    ) -> dpdata.System : 
        return dpdata.System(str(fname), fmt = fmt, type_map = type_map)

    @staticmethod
    def _load_model_devi(
            fname : Path,
    ) -> Tuple[np.array, np.array] : 
        dd = np.loadtxt(fname)
        return dd[:,4], dd[:,1]
