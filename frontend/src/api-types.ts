export type Kind = "call" | "put";
export interface Contract {
  id: string;
  kind: Kind;
  strike: number;
  expiry: number;
  iv: number;
  open_interest: number;
  multiplier: number;
}
export interface ExposureRequest {
  observed_at: number;
  available_at: number;
  valued_at: number;
  spot: number;
  contracts: Contract[];
}
export interface Strike {
  strike: number;
  call: number;
  put: number;
}
export interface ExposureResponse {
  signed: number;
  absolute: number;
  strikes: Strike[];
}
