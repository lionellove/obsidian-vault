import sys

from alfworld.agents.environment import get_environment
import alfworld.agents.modules.generic as generic


MAX_STEPS = 50


def main():
    # generic.load_config() 会从命令行读取 config yaml
    config = generic.load_config()

    # 应该是 AlfredTWEnv
    env_type = config["env"]["type"]
    print(f"Environment type: {env_type}")

    # 先跑 train，单纯验证环境
    env = get_environment(env_type)(
        config,
        train_eval="train",
    )

    # ALFWorld 支持 batch，这里先只跑一个 task
    env = env.init_env(batch_size=1)

    # 开始一个 episode
    obs, info = env.reset()

    print("\n" + "=" * 80)
    print("INITIAL OBSERVATION")
    print("=" * 80)
    print(obs[0])

    for step in range(MAX_STEPS):
        print("\n" + "=" * 80)
        print(f"STEP {step + 1}")
        print("=" * 80)

        # 当前状态下合法的动作
        actions = list(info["admissible_commands"][0])

        print("\nAvailable actions:")
        for action in actions:
            print(f"- {action}")

        # 手动选择动作
        while True:
            user_input = input("\nChoose exact action string (q to quit): ").strip()

            if user_input.lower() == "q":
                print("Quit.")
                return

            if user_input in actions:
                action = user_input
                break
            print("Invalid action; copy one exact admissible action.")

        print(f"\nAction: {action}")

        # ALFWorld 是 batch interface，所以 action 要放在 list 中
        obs, scores, dones, info = env.step([action])

        print("\nObservation:")
        print(obs[0])

        print(f"\nScore: {scores[0]}")
        print(f"Done:  {dones[0]}")

        if dones[0]:
            print("\n" + "=" * 80)
            print("EPISODE FINISHED")
            print("=" * 80)

            if "won" in info:
                print(f"Won: {info['won'][0]}")

            break

    else:
        print(f"\nReached max steps: {MAX_STEPS}")


if __name__ == "__main__":
    main()
