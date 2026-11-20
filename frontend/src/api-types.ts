export type Kind = "call" | "put";
export type Contract = {
  id: string;
  kind: Kind;
  strike: number;
  expiry: number;
  iv: number;
  open_interest: number;
  multiplier: number;
};
export type ExposureRequest = {
  observed_at: number;
  available_at: number;
  valued_at: number;
  spot: number;
  contracts: Array<Contract>;
};
export type Strike = { strike: number; call: number; put: number };
export type ExposureResponse = {
  signed: number;
  absolute: number;
  strikes: Array<Strike>;
};
