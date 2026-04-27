<template>
    <div class="max-w-6xl mx-auto px-4 py-8 flex flex-col lg:flex-row gap-6" style="overflow-y: scroll">

      <!-- 侧边导航（桌面端） -->
      <div class="hidden lg:block w-56 h-fit sticky top-24 bg-white p-4 rounded-lg shadow-sm">
          <p class="text-sm font-medium text-gray-700 mb-3">目录导航</p>
          <div class="space-y-2 text-sm">
              <div><a href="#intro" class="block py-1 pl-2 hover:text-blue-600">课程简介</a></div>
              <div><a href="#target" class="block py-1 pl-2 hover:text-blue-600">课程目标</a></div>
              <div><a href="#plan" class="block py-1 pl-2 hover:text-blue-600">教学计划</a></div>
              <div><a href="#book" class="block py-1 pl-2 hover:text-blue-600">教材与参考资料</a></div>
          </div>
      </div>

      <!-- 移动端浮动菜单 -->
      <div class="lg:hidden fixed right-4 bottom-8 z-50">
          <button id="menuBtn" class="w-12 h-12 rounded-full bg-blue-600 text-white shadow-lg flex items-center justify-center">
              <i class="fa fa-list"></i>
          </button>
      </div>
      <div id="mobileMenu" class="hidden fixed inset-0 bg-black bg-opacity-50 z-40">
          <div class="absolute right-0 bottom-0 w-3/4 bg-white rounded-t-lg p-4 max-h-[70vh] overflow-y-auto">
              <div class="flex justify-between items-center mb-3">
                  <p class="font-medium">目录导航</p>
                  <button id="closeMenu" class="text-gray-500"><i class="fa fa-times"></i></button>
              </div>
              <div class="space-y-3">
                  <a href="#intro" class="block py-2 px-2 rounded hover:bg-blue-50">课程简介</a>
                  <a href="#target" class="block py-2 px-2 rounded hover:bg-blue-50">课程目标</a>
                  <a href="#plan" class="block py-2 px-2 rounded hover:bg-blue-50">教学计划</a>
                  <a href="#book" class="block py-2 px-2 rounded hover:bg-blue-50">教材与参考资料</a>
              </div>
          </div>
      </div>

      <!-- 正文内容 -->
      <div class="flex-1 space-y-6">

          <!-- 标题区 -->
          <div class="bg-white rounded-lg shadow-sm p-6">
              <h1 class="text-2xl font-bold text-gray-800">《程序设计与算法基础II》课程教学大纲</h1>
              <p class="text-gray-500 mt-1">Programming and Algorithms II</p>
              <div class="flex flex-wrap gap-2 mt-4">
                  <span class="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded">学科基础课</span>
                  <span class="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded">软件工程专业</span>
                  <span class="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded">48学时</span>
                  <span class="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded">3学分</span>
                  <span class="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded">先修：C语言、高等数学</span>
              </div>
          </div>

          <!-- 课程简介 -->
          <div id="intro" class="bg-white rounded-lg shadow-sm p-6">
              <h2 class="text-lg font-bold text-gray-800 pl-3 border-l-4 border-blue-600">一、课程简介</h2>
              <div class="mt-4 text-gray-700 space-y-3 text-sm leading-relaxed">
                  <p class="text-indent-2">本课程是计算机程序设计的重要理论技术基础，是软件工程专业的核心课程。课程将介绍几种常见的数据结构，主要包括：数组、队列、堆栈等线性结构，以及树、二叉树、平衡二叉树、图等非线性结构。</p>
                  <p class="text-indent-2">在此基础上，学生可以学习到查找与排序方面的经典算法，掌握这些数据结构的特点、存储结构、操作方法及应用领域，具备根据实际应用设计合理数据结构与高效算法的能力。</p>
                  <p class="text-indent-2">课程内容不仅是后继<span class="text-blue-600 font-medium">编译原理、计算机网络、操作系统</span>等课程的理论基础，而且广泛应用于<span class="text-blue-600 font-medium">图像处理、数据挖掘、科学计算</span>等领域。</p>
              </div>
          </div>

          <!-- 课程目标 -->
          <div id="target" class="bg-white rounded-lg shadow-sm p-6">
              <h2 class="text-lg font-bold text-gray-800 pl-3 border-l-4 border-blue-600">二、课程目标</h2>
              <div class="mt-4 text-sm text-gray-700">
                  <p class="mb-3">课程采用OBE成果导向教育模式，使学生达成以下目标：</p>
                  <ul class="list-disc pl-5 space-y-1">
                      <li>理解各类典型数据结构的逻辑结构与存储结构</li>
                      <li>掌握常用算法的设计思想、实现方法与性能分析</li>
                      <li>具备运用数据结构与算法解决实际问题的能力</li>
                      <li>具备良好的程序设计规范与工程实践意识</li>
                  </ul>
              </div>
          </div>

          <!-- 教学计划 -->
          <div id="plan" class="bg-white rounded-lg shadow-sm p-6">
              <h2 class="text-lg font-bold text-gray-800 pl-3 border-l-4 border-blue-600">三、教学计划与内容</h2>
              <div class="mt-5 space-y-4">

                  <div class="border rounded-lg p-4 bg-gray-50">
                      <h3 class="font-medium text-blue-700">第1章 绪论</h3>
                      <p class="text-xs text-gray-500 mt-1">3 学时 | 教学方式：课堂讲授</p>
                      <div class="mt-2 text-sm text-gray-700 space-y-2">
                          <p>• 数据结构基本概念</p>
                          <p>• 算法及其描述方法</p>
                          <p>• 时间复杂度与空间复杂度分析</p>
                          <p class="text-orange-600 font-medium">重点：复杂度分析方法</p>
                      </div>
                  </div>

                  <div class="border rounded-lg p-4 bg-gray-50">
                      <h3 class="font-medium text-blue-700">第2章 线性表</h3>
                      <p class="text-xs text-gray-500 mt-1">6 学时 | 教学方式：讲授 + 实验</p>
                      <div class="mt-2 text-sm text-gray-700 space-y-2">
                          <p>• 顺序表与链表</p>
                          <p>• 插入、删除、查找操作</p>
                          <p>• 单链表、双链表、循环链表实现</p>
                          <p class="text-orange-600 font-medium">重点：链表操作与应用</p>
                      </div>
                  </div>

                  <div class="border rounded-lg p-4 bg-gray-50">
                      <h3 class="font-medium text-blue-700">第3章 栈和队列</h3>
                      <p class="text-xs text-gray-500 mt-1">6 学时 | 教学方式：讲授 + 实验</p>
                      <div class="mt-2 text-sm text-gray-700 space-y-2">
                          <p>• 栈的结构与应用</p>
                          <p>• 队列与循环队列</p>
                          <p>• 栈与递归的关系</p>
                          <p class="text-orange-600 font-medium">重点：栈在表达式求值中的应用</p>
                      </div>
                  </div>

                  <div class="border rounded-lg p-4 bg-gray-50">
                      <h3 class="font-medium text-blue-700">第4章 树与二叉树</h3>
                      <p class="text-xs text-gray-500 mt-1">8 学时 | 教学方式：讲授 + 实验</p>
                      <div class="mt-2 text-sm text-gray-700 space-y-2">
                          <p>• 树的基本概念</p>
                          <p>• 二叉树性质与存储</p>
                          <p>• 二叉树遍历（前/中/后/层序）</p>
                          <p>• 哈夫曼树与应用</p>
                          <p class="text-orange-600 font-medium">重点与难点：二叉树遍历与递归实现</p>
                      </div>
                  </div>

                  <div class="border rounded-lg p-4 bg-gray-50">
                      <h3 class="font-medium text-blue-700">第5章 图</h3>
                      <p class="text-xs text-gray-500 mt-1">8 学时 | 教学方式：讲授 + 实验</p>
                      <div class="mt-2 text-sm text-gray-700 space-y-2">
                          <p>• 图的定义、存储结构（邻接矩阵/邻接表）</p>
                          <p>• 图的遍历（DFS、BFS）</p>
                          <p>• 最小生成树、最短路径</p>
                          <p>• 拓扑排序与关键路径</p>
                          <p class="text-orange-600 font-medium">重点：图遍历与路径算法</p>
                      </div>
                  </div>

                  <div class="border rounded-lg p-4 bg-gray-50">
                      <h3 class="font-medium text-blue-700">第6章 查找与排序</h3>
                      <p class="text-xs text-gray-500 mt-1">10 学时 | 教学方式：讲授 + 实验</p>
                      <div class="mt-2 text-sm text-gray-700 space-y-2">
                          <p>• 顺序查找、二分查找</p>
                          <p>• 插入排序、冒泡排序、选择排序</p>
                          <p>• 快速排序、堆排序、归并排序</p>
                          <p>• 各种算法性能对比与适用场景</p>
                          <p class="text-orange-600 font-medium">重点：快排、归并排序、二分查找</p>
                      </div>
                  </div>
              </div>
          </div>

          <!-- 教材与参考资料 -->
          <div id="book" class="bg-white rounded-lg shadow-sm p-6">
              <h2 class="text-lg font-bold text-gray-800 pl-3 border-l-4 border-blue-600">四、建议教材及参考资料</h2>
              <div class="mt-4 text-sm text-gray-700 space-y-4">
                  <div>
                      <p class="font-medium">教材：</p>
                      <p class="pl-2">数据结构(C语言版). 严蔚敏, 吴伟民. 清华大学出版社.</p>
                  </div>
                  <div>
                      <p class="font-medium">参考资料：</p>
                      <ul class="pl-2 space-y-1">
                          <li>Data Structures and Algorithm Analysis in C, Mark Allen Weiss</li>
                          <li>算法导论. Thomas H.Cormen 等. 机械工业出版社.</li>
                          <li>数据结构与算法分析. 浙江大学 陈越.</li>
                      </ul>
                  </div>
              </div>
          </div>
      </div>
  </div>
</template>

<script>
    // const menuBtn = document.getElementById('menuBtn')
    // const mobileMenu = document.getElementById('mobileMenu')
    // const closeMenu = document.getElementById('closeMenu')
    // menuBtn.addEventListener('click', () => {
    //     mobileMenu.classList.toggle('hidden')
    // })
    // closeMenu.addEventListener('click', () => {
    //     mobileMenu.classList.add('hidden')
    // })
    // document.querySelectorAll('#mobileMenu a').forEach(a => {
    //     a.addEventListener('click', () => {
    //         mobileMenu.classList.add('hidden')
    //     })
    // })
</script>

<style scoped>
  .text-indent-2 { text-indent: 2em; }
  .anchor-active { border-left: 3px solid #165DFF; color: #165DFF; font-weight: 500; }
  template { scroll-behavior: smooth; }
</style>