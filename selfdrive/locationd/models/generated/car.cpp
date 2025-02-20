#include "car.h"

namespace {
#define DIM 9
#define EDIM 9
#define MEDIM 9
typedef void (*Hfun)(double *, double *, double *);

double mass;

void set_mass(double x){ mass = x;}

double rotational_inertia;

void set_rotational_inertia(double x){ rotational_inertia = x;}

double center_to_front;

void set_center_to_front(double x){ center_to_front = x;}

double center_to_rear;

void set_center_to_rear(double x){ center_to_rear = x;}

double stiffness_front;

void set_stiffness_front(double x){ stiffness_front = x;}

double stiffness_rear;

void set_stiffness_rear(double x){ stiffness_rear = x;}
const static double MAHA_THRESH_25 = 3.8414588206941227;
const static double MAHA_THRESH_24 = 5.991464547107981;
const static double MAHA_THRESH_30 = 3.8414588206941227;
const static double MAHA_THRESH_26 = 3.8414588206941227;
const static double MAHA_THRESH_27 = 3.8414588206941227;
const static double MAHA_THRESH_29 = 3.8414588206941227;
const static double MAHA_THRESH_28 = 3.8414588206941227;
const static double MAHA_THRESH_31 = 3.8414588206941227;

/******************************************************************************
 *                       Code generated with SymPy 1.12                       *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_2426188779899270877) {
   out_2426188779899270877[0] = delta_x[0] + nom_x[0];
   out_2426188779899270877[1] = delta_x[1] + nom_x[1];
   out_2426188779899270877[2] = delta_x[2] + nom_x[2];
   out_2426188779899270877[3] = delta_x[3] + nom_x[3];
   out_2426188779899270877[4] = delta_x[4] + nom_x[4];
   out_2426188779899270877[5] = delta_x[5] + nom_x[5];
   out_2426188779899270877[6] = delta_x[6] + nom_x[6];
   out_2426188779899270877[7] = delta_x[7] + nom_x[7];
   out_2426188779899270877[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_6034937303263587821) {
   out_6034937303263587821[0] = -nom_x[0] + true_x[0];
   out_6034937303263587821[1] = -nom_x[1] + true_x[1];
   out_6034937303263587821[2] = -nom_x[2] + true_x[2];
   out_6034937303263587821[3] = -nom_x[3] + true_x[3];
   out_6034937303263587821[4] = -nom_x[4] + true_x[4];
   out_6034937303263587821[5] = -nom_x[5] + true_x[5];
   out_6034937303263587821[6] = -nom_x[6] + true_x[6];
   out_6034937303263587821[7] = -nom_x[7] + true_x[7];
   out_6034937303263587821[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_2579187332183547104) {
   out_2579187332183547104[0] = 1.0;
   out_2579187332183547104[1] = 0;
   out_2579187332183547104[2] = 0;
   out_2579187332183547104[3] = 0;
   out_2579187332183547104[4] = 0;
   out_2579187332183547104[5] = 0;
   out_2579187332183547104[6] = 0;
   out_2579187332183547104[7] = 0;
   out_2579187332183547104[8] = 0;
   out_2579187332183547104[9] = 0;
   out_2579187332183547104[10] = 1.0;
   out_2579187332183547104[11] = 0;
   out_2579187332183547104[12] = 0;
   out_2579187332183547104[13] = 0;
   out_2579187332183547104[14] = 0;
   out_2579187332183547104[15] = 0;
   out_2579187332183547104[16] = 0;
   out_2579187332183547104[17] = 0;
   out_2579187332183547104[18] = 0;
   out_2579187332183547104[19] = 0;
   out_2579187332183547104[20] = 1.0;
   out_2579187332183547104[21] = 0;
   out_2579187332183547104[22] = 0;
   out_2579187332183547104[23] = 0;
   out_2579187332183547104[24] = 0;
   out_2579187332183547104[25] = 0;
   out_2579187332183547104[26] = 0;
   out_2579187332183547104[27] = 0;
   out_2579187332183547104[28] = 0;
   out_2579187332183547104[29] = 0;
   out_2579187332183547104[30] = 1.0;
   out_2579187332183547104[31] = 0;
   out_2579187332183547104[32] = 0;
   out_2579187332183547104[33] = 0;
   out_2579187332183547104[34] = 0;
   out_2579187332183547104[35] = 0;
   out_2579187332183547104[36] = 0;
   out_2579187332183547104[37] = 0;
   out_2579187332183547104[38] = 0;
   out_2579187332183547104[39] = 0;
   out_2579187332183547104[40] = 1.0;
   out_2579187332183547104[41] = 0;
   out_2579187332183547104[42] = 0;
   out_2579187332183547104[43] = 0;
   out_2579187332183547104[44] = 0;
   out_2579187332183547104[45] = 0;
   out_2579187332183547104[46] = 0;
   out_2579187332183547104[47] = 0;
   out_2579187332183547104[48] = 0;
   out_2579187332183547104[49] = 0;
   out_2579187332183547104[50] = 1.0;
   out_2579187332183547104[51] = 0;
   out_2579187332183547104[52] = 0;
   out_2579187332183547104[53] = 0;
   out_2579187332183547104[54] = 0;
   out_2579187332183547104[55] = 0;
   out_2579187332183547104[56] = 0;
   out_2579187332183547104[57] = 0;
   out_2579187332183547104[58] = 0;
   out_2579187332183547104[59] = 0;
   out_2579187332183547104[60] = 1.0;
   out_2579187332183547104[61] = 0;
   out_2579187332183547104[62] = 0;
   out_2579187332183547104[63] = 0;
   out_2579187332183547104[64] = 0;
   out_2579187332183547104[65] = 0;
   out_2579187332183547104[66] = 0;
   out_2579187332183547104[67] = 0;
   out_2579187332183547104[68] = 0;
   out_2579187332183547104[69] = 0;
   out_2579187332183547104[70] = 1.0;
   out_2579187332183547104[71] = 0;
   out_2579187332183547104[72] = 0;
   out_2579187332183547104[73] = 0;
   out_2579187332183547104[74] = 0;
   out_2579187332183547104[75] = 0;
   out_2579187332183547104[76] = 0;
   out_2579187332183547104[77] = 0;
   out_2579187332183547104[78] = 0;
   out_2579187332183547104[79] = 0;
   out_2579187332183547104[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_1939839960763914049) {
   out_1939839960763914049[0] = state[0];
   out_1939839960763914049[1] = state[1];
   out_1939839960763914049[2] = state[2];
   out_1939839960763914049[3] = state[3];
   out_1939839960763914049[4] = state[4];
   out_1939839960763914049[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8000000000000007*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_1939839960763914049[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_1939839960763914049[7] = state[7];
   out_1939839960763914049[8] = state[8];
}
void F_fun(double *state, double dt, double *out_4233304103879758867) {
   out_4233304103879758867[0] = 1;
   out_4233304103879758867[1] = 0;
   out_4233304103879758867[2] = 0;
   out_4233304103879758867[3] = 0;
   out_4233304103879758867[4] = 0;
   out_4233304103879758867[5] = 0;
   out_4233304103879758867[6] = 0;
   out_4233304103879758867[7] = 0;
   out_4233304103879758867[8] = 0;
   out_4233304103879758867[9] = 0;
   out_4233304103879758867[10] = 1;
   out_4233304103879758867[11] = 0;
   out_4233304103879758867[12] = 0;
   out_4233304103879758867[13] = 0;
   out_4233304103879758867[14] = 0;
   out_4233304103879758867[15] = 0;
   out_4233304103879758867[16] = 0;
   out_4233304103879758867[17] = 0;
   out_4233304103879758867[18] = 0;
   out_4233304103879758867[19] = 0;
   out_4233304103879758867[20] = 1;
   out_4233304103879758867[21] = 0;
   out_4233304103879758867[22] = 0;
   out_4233304103879758867[23] = 0;
   out_4233304103879758867[24] = 0;
   out_4233304103879758867[25] = 0;
   out_4233304103879758867[26] = 0;
   out_4233304103879758867[27] = 0;
   out_4233304103879758867[28] = 0;
   out_4233304103879758867[29] = 0;
   out_4233304103879758867[30] = 1;
   out_4233304103879758867[31] = 0;
   out_4233304103879758867[32] = 0;
   out_4233304103879758867[33] = 0;
   out_4233304103879758867[34] = 0;
   out_4233304103879758867[35] = 0;
   out_4233304103879758867[36] = 0;
   out_4233304103879758867[37] = 0;
   out_4233304103879758867[38] = 0;
   out_4233304103879758867[39] = 0;
   out_4233304103879758867[40] = 1;
   out_4233304103879758867[41] = 0;
   out_4233304103879758867[42] = 0;
   out_4233304103879758867[43] = 0;
   out_4233304103879758867[44] = 0;
   out_4233304103879758867[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_4233304103879758867[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_4233304103879758867[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_4233304103879758867[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_4233304103879758867[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_4233304103879758867[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_4233304103879758867[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_4233304103879758867[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_4233304103879758867[53] = -9.8000000000000007*dt;
   out_4233304103879758867[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_4233304103879758867[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_4233304103879758867[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4233304103879758867[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4233304103879758867[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_4233304103879758867[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_4233304103879758867[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_4233304103879758867[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4233304103879758867[62] = 0;
   out_4233304103879758867[63] = 0;
   out_4233304103879758867[64] = 0;
   out_4233304103879758867[65] = 0;
   out_4233304103879758867[66] = 0;
   out_4233304103879758867[67] = 0;
   out_4233304103879758867[68] = 0;
   out_4233304103879758867[69] = 0;
   out_4233304103879758867[70] = 1;
   out_4233304103879758867[71] = 0;
   out_4233304103879758867[72] = 0;
   out_4233304103879758867[73] = 0;
   out_4233304103879758867[74] = 0;
   out_4233304103879758867[75] = 0;
   out_4233304103879758867[76] = 0;
   out_4233304103879758867[77] = 0;
   out_4233304103879758867[78] = 0;
   out_4233304103879758867[79] = 0;
   out_4233304103879758867[80] = 1;
}
void h_25(double *state, double *unused, double *out_3837027921546495142) {
   out_3837027921546495142[0] = state[6];
}
void H_25(double *state, double *unused, double *out_6867692706641622056) {
   out_6867692706641622056[0] = 0;
   out_6867692706641622056[1] = 0;
   out_6867692706641622056[2] = 0;
   out_6867692706641622056[3] = 0;
   out_6867692706641622056[4] = 0;
   out_6867692706641622056[5] = 0;
   out_6867692706641622056[6] = 1;
   out_6867692706641622056[7] = 0;
   out_6867692706641622056[8] = 0;
}
void h_24(double *state, double *unused, double *out_5937149318244275864) {
   out_5937149318244275864[0] = state[4];
   out_5937149318244275864[1] = state[5];
}
void H_24(double *state, double *unused, double *out_7338150188684960780) {
   out_7338150188684960780[0] = 0;
   out_7338150188684960780[1] = 0;
   out_7338150188684960780[2] = 0;
   out_7338150188684960780[3] = 0;
   out_7338150188684960780[4] = 1;
   out_7338150188684960780[5] = 0;
   out_7338150188684960780[6] = 0;
   out_7338150188684960780[7] = 0;
   out_7338150188684960780[8] = 0;
   out_7338150188684960780[9] = 0;
   out_7338150188684960780[10] = 0;
   out_7338150188684960780[11] = 0;
   out_7338150188684960780[12] = 0;
   out_7338150188684960780[13] = 0;
   out_7338150188684960780[14] = 1;
   out_7338150188684960780[15] = 0;
   out_7338150188684960780[16] = 0;
   out_7338150188684960780[17] = 0;
}
void h_30(double *state, double *unused, double *out_3679841253195365997) {
   out_3679841253195365997[0] = state[4];
}
void H_30(double *state, double *unused, double *out_6997031653784862126) {
   out_6997031653784862126[0] = 0;
   out_6997031653784862126[1] = 0;
   out_6997031653784862126[2] = 0;
   out_6997031653784862126[3] = 0;
   out_6997031653784862126[4] = 1;
   out_6997031653784862126[5] = 0;
   out_6997031653784862126[6] = 0;
   out_6997031653784862126[7] = 0;
   out_6997031653784862126[8] = 0;
}
void h_26(double *state, double *unused, double *out_8642221250876659229) {
   out_8642221250876659229[0] = state[7];
}
void H_26(double *state, double *unused, double *out_7837548048193873336) {
   out_7837548048193873336[0] = 0;
   out_7837548048193873336[1] = 0;
   out_7837548048193873336[2] = 0;
   out_7837548048193873336[3] = 0;
   out_7837548048193873336[4] = 0;
   out_7837548048193873336[5] = 0;
   out_7837548048193873336[6] = 0;
   out_7837548048193873336[7] = 1;
   out_7837548048193873336[8] = 0;
}
void h_27(double *state, double *unused, double *out_8760228644810035973) {
   out_8760228644810035973[0] = state[3];
}
void H_27(double *state, double *unused, double *out_9171794965585287037) {
   out_9171794965585287037[0] = 0;
   out_9171794965585287037[1] = 0;
   out_9171794965585287037[2] = 0;
   out_9171794965585287037[3] = 1;
   out_9171794965585287037[4] = 0;
   out_9171794965585287037[5] = 0;
   out_9171794965585287037[6] = 0;
   out_9171794965585287037[7] = 0;
   out_9171794965585287037[8] = 0;
}
void h_29(double *state, double *unused, double *out_5746359408073709177) {
   out_5746359408073709177[0] = state[1];
}
void H_29(double *state, double *unused, double *out_7561586381254713546) {
   out_7561586381254713546[0] = 0;
   out_7561586381254713546[1] = 1;
   out_7561586381254713546[2] = 0;
   out_7561586381254713546[3] = 0;
   out_7561586381254713546[4] = 0;
   out_7561586381254713546[5] = 0;
   out_7561586381254713546[6] = 0;
   out_7561586381254713546[7] = 0;
   out_7561586381254713546[8] = 0;
}
void h_28(double *state, double *unused, double *out_4684842161238669998) {
   out_4684842161238669998[0] = state[0];
}
void H_28(double *state, double *unused, double *out_2479187364185182972) {
   out_2479187364185182972[0] = 1;
   out_2479187364185182972[1] = 0;
   out_2479187364185182972[2] = 0;
   out_2479187364185182972[3] = 0;
   out_2479187364185182972[4] = 0;
   out_2479187364185182972[5] = 0;
   out_2479187364185182972[6] = 0;
   out_2479187364185182972[7] = 0;
   out_2479187364185182972[8] = 0;
}
void h_31(double *state, double *unused, double *out_7149157387914168149) {
   out_7149157387914168149[0] = state[8];
}
void H_31(double *state, double *unused, double *out_6837046744764661628) {
   out_6837046744764661628[0] = 0;
   out_6837046744764661628[1] = 0;
   out_6837046744764661628[2] = 0;
   out_6837046744764661628[3] = 0;
   out_6837046744764661628[4] = 0;
   out_6837046744764661628[5] = 0;
   out_6837046744764661628[6] = 0;
   out_6837046744764661628[7] = 0;
   out_6837046744764661628[8] = 1;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_25, H_25, NULL, in_z, in_R, in_ea, MAHA_THRESH_25);
}
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<2, 3, 0>(in_x, in_P, h_24, H_24, NULL, in_z, in_R, in_ea, MAHA_THRESH_24);
}
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_30, H_30, NULL, in_z, in_R, in_ea, MAHA_THRESH_30);
}
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_26, H_26, NULL, in_z, in_R, in_ea, MAHA_THRESH_26);
}
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_27, H_27, NULL, in_z, in_R, in_ea, MAHA_THRESH_27);
}
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_29, H_29, NULL, in_z, in_R, in_ea, MAHA_THRESH_29);
}
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_28, H_28, NULL, in_z, in_R, in_ea, MAHA_THRESH_28);
}
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_31, H_31, NULL, in_z, in_R, in_ea, MAHA_THRESH_31);
}
void car_err_fun(double *nom_x, double *delta_x, double *out_2426188779899270877) {
  err_fun(nom_x, delta_x, out_2426188779899270877);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_6034937303263587821) {
  inv_err_fun(nom_x, true_x, out_6034937303263587821);
}
void car_H_mod_fun(double *state, double *out_2579187332183547104) {
  H_mod_fun(state, out_2579187332183547104);
}
void car_f_fun(double *state, double dt, double *out_1939839960763914049) {
  f_fun(state,  dt, out_1939839960763914049);
}
void car_F_fun(double *state, double dt, double *out_4233304103879758867) {
  F_fun(state,  dt, out_4233304103879758867);
}
void car_h_25(double *state, double *unused, double *out_3837027921546495142) {
  h_25(state, unused, out_3837027921546495142);
}
void car_H_25(double *state, double *unused, double *out_6867692706641622056) {
  H_25(state, unused, out_6867692706641622056);
}
void car_h_24(double *state, double *unused, double *out_5937149318244275864) {
  h_24(state, unused, out_5937149318244275864);
}
void car_H_24(double *state, double *unused, double *out_7338150188684960780) {
  H_24(state, unused, out_7338150188684960780);
}
void car_h_30(double *state, double *unused, double *out_3679841253195365997) {
  h_30(state, unused, out_3679841253195365997);
}
void car_H_30(double *state, double *unused, double *out_6997031653784862126) {
  H_30(state, unused, out_6997031653784862126);
}
void car_h_26(double *state, double *unused, double *out_8642221250876659229) {
  h_26(state, unused, out_8642221250876659229);
}
void car_H_26(double *state, double *unused, double *out_7837548048193873336) {
  H_26(state, unused, out_7837548048193873336);
}
void car_h_27(double *state, double *unused, double *out_8760228644810035973) {
  h_27(state, unused, out_8760228644810035973);
}
void car_H_27(double *state, double *unused, double *out_9171794965585287037) {
  H_27(state, unused, out_9171794965585287037);
}
void car_h_29(double *state, double *unused, double *out_5746359408073709177) {
  h_29(state, unused, out_5746359408073709177);
}
void car_H_29(double *state, double *unused, double *out_7561586381254713546) {
  H_29(state, unused, out_7561586381254713546);
}
void car_h_28(double *state, double *unused, double *out_4684842161238669998) {
  h_28(state, unused, out_4684842161238669998);
}
void car_H_28(double *state, double *unused, double *out_2479187364185182972) {
  H_28(state, unused, out_2479187364185182972);
}
void car_h_31(double *state, double *unused, double *out_7149157387914168149) {
  h_31(state, unused, out_7149157387914168149);
}
void car_H_31(double *state, double *unused, double *out_6837046744764661628) {
  H_31(state, unused, out_6837046744764661628);
}
void car_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
void car_set_mass(double x) {
  set_mass(x);
}
void car_set_rotational_inertia(double x) {
  set_rotational_inertia(x);
}
void car_set_center_to_front(double x) {
  set_center_to_front(x);
}
void car_set_center_to_rear(double x) {
  set_center_to_rear(x);
}
void car_set_stiffness_front(double x) {
  set_stiffness_front(x);
}
void car_set_stiffness_rear(double x) {
  set_stiffness_rear(x);
}
}

const EKF car = {
  .name = "car",
  .kinds = { 25, 24, 30, 26, 27, 29, 28, 31 },
  .feature_kinds = {  },
  .f_fun = car_f_fun,
  .F_fun = car_F_fun,
  .err_fun = car_err_fun,
  .inv_err_fun = car_inv_err_fun,
  .H_mod_fun = car_H_mod_fun,
  .predict = car_predict,
  .hs = {
    { 25, car_h_25 },
    { 24, car_h_24 },
    { 30, car_h_30 },
    { 26, car_h_26 },
    { 27, car_h_27 },
    { 29, car_h_29 },
    { 28, car_h_28 },
    { 31, car_h_31 },
  },
  .Hs = {
    { 25, car_H_25 },
    { 24, car_H_24 },
    { 30, car_H_30 },
    { 26, car_H_26 },
    { 27, car_H_27 },
    { 29, car_H_29 },
    { 28, car_H_28 },
    { 31, car_H_31 },
  },
  .updates = {
    { 25, car_update_25 },
    { 24, car_update_24 },
    { 30, car_update_30 },
    { 26, car_update_26 },
    { 27, car_update_27 },
    { 29, car_update_29 },
    { 28, car_update_28 },
    { 31, car_update_31 },
  },
  .Hes = {
  },
  .sets = {
    { "mass", car_set_mass },
    { "rotational_inertia", car_set_rotational_inertia },
    { "center_to_front", car_set_center_to_front },
    { "center_to_rear", car_set_center_to_rear },
    { "stiffness_front", car_set_stiffness_front },
    { "stiffness_rear", car_set_stiffness_rear },
  },
  .extra_routines = {
  },
};

ekf_lib_init(car)
