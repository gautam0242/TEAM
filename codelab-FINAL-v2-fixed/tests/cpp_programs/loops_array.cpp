#include <iostream>
int main(){ int a[5]={5,3,9,1,7}; int m=a[0]; for(int i=1;i<5;i++) if(a[i]>m) m=a[i]; int s=0; for(int x:a) s+=x; std::cout<<m<<" "<<s<<"\n"; }
