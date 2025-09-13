import sys
import argparse
import os
import atexit
import threading

executor = None

def _cleanup_on_exit():
    """
    Function to be called automatically at program exit to perform cleanup.
    """
    if executor:
        print("[Network Chaos] Program exiting. Performing cleanup...")
        executor.cleanup()

def main():
    global executor
    parser = argparse.ArgumentParser(
        description='Network Chaos - Declarative DSL for network chaos experiments'
    )
    parser.add_argument(
        'file',
        type=str,
        help='Path to the .chaos file containing DSL script'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be executed without actually applying changes'
    )
    parser.add_argument(
        '--target',
        type=str,
        choices=['kubernetes', 'docker'],
        default='kubernetes',
        help='The target environment for chaos injection (default: kubernetes)'
    )
    parser.add_argument(
        '--prom-url',
        type=str,
        default='http://localhost:9090',
        help='URL of the Prometheus HTTP API (default: http://localhost:9090)'
    )
    parser.add_argument(
        '--visualize',
        action='store_true',
        help='Generate a Graphviz DOT file of the scenario instead of executing it'
    )
    
    args = parser.parse_args()
    
    atexit.register(_cleanup_on_exit)

    try:
        try:
            with open(args.file, 'r') as f:
                dsl_content = f.read()
        except FileNotFoundError:
            print(f"[Network Chaos] ERROR: File not found: {args.file}")
            sys.exit(1)
        except Exception as e:
            print(f"[Network Chaos] ERROR: Failed to read file: {e}")
            sys.exit(1)
        
        print(f"[Network Chaos] Parsing {args.file}...")
        from src.parser import Parser
        chaos_parser = Parser()
        
        try:
            ast = chaos_parser.parse(dsl_content)
            print("[Network Chaos] Parsing successful!")
        except Exception as e:
            print(f"[Network Chaos] ERROR: Failed to parse DSL: {e}")
            sys.exit(1)
        
        if args.visualize:
            print("[Network Chaos] Generating Graphviz DOT file...")
            from src.visualizer import Visualizer
            visualizer = Visualizer()
            dot_string = visualizer.generate_dot(ast)
            
            output_file = f"{os.path.basename(args.file)}.dot"
            with open(output_file, "w") as f:
                f.write(dot_string)
            print(f"[Network Chaos] DOT file saved to '{output_file}'.")
            print("To generate an image, install Graphviz and run:")
            print(f"  dot -Tpng {output_file} -o {os.path.splitext(output_file)[0]}.png")
            
        else:
            from src.executor import Executor
            executor = Executor(
                dry_run=args.dry_run,
                target=args.target,
                prom_endpoint=args.prom_url
            )
            executor.execute(ast)
            
    except Exception as e:
        print(f"[Network Chaos] An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        print("[Network Chaos] Execution finished.")

if __name__ == '__main__':
    main()
