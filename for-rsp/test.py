# make the function of calculating factorial
import argparse

def factorial(n):
    if n == 0 or n == 1:
        return 1
    else:
        return n * factorial(n - 1)     
    
# create a function to generate fibonacci sequence of a given array
def fibonacci_sequence(arr):
    def fibonacci(n):
        if n == 0:
            return 0
        elif n == 1:
            return 1
        else:
            return fibonacci(n - 1) + fibonacci(n - 2)

    return [fibonacci(n) for n in arr]

def main():
    # set argument for command line 
    argument_parser = argparse.ArgumentParser(description='Calculate factorial of a number')
    argument_parser.add_argument('number', type=int, help='A non-negative integer')
    args = argument_parser.parse_args()

    print(factorial(args.number))  # Output: 120
    print(fibonacci_sequence([1, 2, 3, 4, 5, 6, 7]))  # Output: [1, 1, 2, 3, 5]

if __name__ == '__main__':
    main()