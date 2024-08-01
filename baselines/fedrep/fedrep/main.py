"""Create and connect the building blocks for your experiments; start the simulation.

It includes processioning the dataset, instantiate strategy, specify how the global
model is going to be evaluated, etc. At the end, this script saves the results.
"""

from pathlib import Path

import flwr as fl
import hydra
from flwr.common.parameter import ndarrays_to_parameters
from hydra.core.hydra_config import HydraConfig
from hydra.utils import instantiate
from omegaconf import DictConfig, OmegaConf


from fedrep.dataset import dataset_main
from fedrep.utils import (
    get_client_fn,
    get_create_model_fn,
    plot_metric_from_history,
    save_results_as_pickle,
    set_client_state_save_path,
    set_model_class,
)


@hydra.main(config_path="conf", config_name="base", version_base=None)
def main(cfg: DictConfig) -> None:
    """Run the baseline.

    Parameters
    ----------
    cfg : DictConfig
        An omegaconf object that stores the hydra config.
    """
    # 1. Print parsed config
    # Set the model class, server target, and number of classes
    set_model_class(cfg)

    create_model_fn, model_split_class = get_create_model_fn(cfg)

    model = model_split_class(create_model_fn())

    print(OmegaConf.to_yaml(cfg))

    # Create directory to store client states if it does not exist
    # Client state has subdirectories with the name of current time
    client_state_save_path = set_client_state_save_path()

    # 2. Prepare your dataset
    dataset_main(cfg.dataset)

    # 3. Define your clients
    # Get client function
    client_fn = get_client_fn(config=cfg, client_state_save_path=client_state_save_path)

    def get_on_fit_config():

        def fit_config_fn(server_round: int):
            # resolve and convert to python dict
            fit_config = OmegaConf.to_container(cfg.fit_config, resolve=True)
            return fit_config

        return fit_config_fn

    # 4. Define your strategy
    strategy = instantiate(
        cfg.strategy,
        model_split_class=model_split_class,
        create_model=create_model_fn,
        initial_parameters=ndarrays_to_parameters(model.get_parameters()),
        on_fit_config_fn=get_on_fit_config(),
    )

    # 5. Start Simulation
    history = fl.simulation.start_simulation(
        client_fn=client_fn,  # type: ignore
        num_clients=cfg.num_clients,
        config=fl.server.ServerConfig(num_rounds=cfg.num_rounds),
        client_resources={
            "num_cpus": cfg.client_resources.num_cpus,
            "num_gpus": cfg.client_resources.num_gpus,
        },
        strategy=strategy,
    )

    # Experiment completed. Now we save the results and
    # generate plots using the `history`
    print("................")
    print(history)

    # 6. Save your results
    save_path = Path(HydraConfig.get().runtime.output_dir)

    # save results as a Python pickle using a file_path
    # the directory created by Hydra for each run
    save_results_as_pickle(history, file_path=save_path)
    # plot results and include them in the readme
    strategy_name = strategy.__class__.__name__
    file_suffix: str = (
        f"_{strategy_name}"
        f"_C={cfg.num_clients}"
        f"_B={cfg.batch_size}"
        f"_E={cfg.num_local_epochs}"
        f"_R={cfg.num_rounds}"
        f"_lr={cfg.learning_rate}"
    )

    plot_metric_from_history(history, save_path, file_suffix)


if __name__ == "__main__":
    main()
