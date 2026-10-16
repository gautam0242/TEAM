#include <iostream>
int fact(int n){ return n<=1?1:n*fact(n-1); }
int fib(int n){ return n<2?n:fib(n-1)+fib(n-2); }
int main(){ std::cout<<fact(10)<<" "<<fib(20)<<"\n"; }
