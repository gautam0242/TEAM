#include <iostream>
int main(){ int n; while(std::cin>>n) std::cout<<(n<0?"neg":n==0?"zero":"pos")<<"\n"; }
