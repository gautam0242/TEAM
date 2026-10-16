#include <iostream>
#include <string>
#include <vector>
#include <algorithm>
int main(){ std::string s="codelab"; std::vector<int> v={5,2,8,1}; std::sort(v.begin(),v.end()); std::cout<<s.size()<<s[0]<<s+"!"; for(int x:v) std::cout<<" "<<x; std::cout<<"\n"; }
